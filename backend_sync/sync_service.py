"""Bidirectional synchronization service for Forge Steel.

Implements offline synchronization protocol between the central database and
client cache (browser IndexedDB / LocalStorage) with:
1. Offline timestamp tracking
2. Conflict resolution (Last-Write-Wins with deterministic server reconciliation)
3. Soft-deletion (tombstone) propagation
4. Incremental pull of server-side mutations
"""

from __future__ import annotations
from datetime import datetime, timezone
from typing import List, Optional, Tuple, Any, Dict
from sqlalchemy.orm import Session
from sqlalchemy import or_

from models import (
    Party,
    Hero,
    Retainer,
    HeroRetainerAssignment,
    SyncRequest,
    SyncResponse,
    SyncChanges,
    SyncServerChanges,
    ConflictDetail,
    PartyResponse,
    HeroResponse,
    RetainerResponse,
    HeroRetainerAssignmentResponse,
    utc_now,
    generate_uuid,
)


def ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Ensure datetime is timezone-aware UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class SyncService:
    """Manages bidirectional sync and conflict resolution."""

    def __init__(self, db: Session):
        self.db = db

    def sync(self, request: SyncRequest) -> SyncResponse:
        """Execute bidirectional sync transaction.
        
        1. Ingest and reconcile client offline changes.
        2. Detect and resolve any concurrent update conflicts.
        3. Gather all server changes since client's last_synced_at.
        4. Return atomic response with current server timestamp.
        """
        last_synced_at = ensure_utc(request.last_synced_at)
        sync_timestamp = utc_now()
        conflicts: List[ConflictDetail] = []
        applied_count = 0

        # --- Phase 1: Ingest Client Changes ---

        # 1. Parties
        for p_item in request.changes.parties:
            applied, conflict = self._reconcile_party(p_item, last_synced_at, sync_timestamp)
            if applied:
                applied_count += 1
            if conflict:
                conflicts.append(conflict)

        # 2. Heroes
        for h_item in request.changes.heroes:
            applied, conflict = self._reconcile_hero(h_item, last_synced_at, sync_timestamp)
            if applied:
                applied_count += 1
            if conflict:
                conflicts.append(conflict)

        # 3. Retainers (Shared Party Roster)
        for r_item in request.changes.retainers:
            applied, conflict = self._reconcile_retainer(r_item, last_synced_at, sync_timestamp)
            if applied:
                applied_count += 1
            if conflict:
                conflicts.append(conflict)

        # 4. Hero-Retainer Assignments
        for a_item in request.changes.assignments:
            applied, conflict = self._reconcile_assignment(a_item, last_synced_at, sync_timestamp)
            if applied:
                applied_count += 1
            if conflict:
                conflicts.append(conflict)

        self.db.commit()

        # --- Phase 2: Gather Server Changes since last_synced_at ---
        server_changes = self._gather_server_changes(last_synced_at)

        return SyncResponse(
            sync_timestamp=sync_timestamp,
            applied_count=applied_count,
            conflicts=conflicts,
            server_changes=server_changes,
        )

    # -------------------------------------------------------------------------
    # Party Reconciliation
    # -------------------------------------------------------------------------

    def _reconcile_party(self, item, last_synced_at: Optional[datetime], sync_timestamp: datetime) -> Tuple[bool, Optional[ConflictDetail]]:
        party = self.db.query(Party).filter(Party.id == item.id).first()
        client_ts = ensure_utc(item.client_updated_at or item.updated_at) or sync_timestamp

        if not party:
            if item.is_deleted:
                return False, None
            party = Party(
                id=item.id,
                name=item.name or "Unnamed Party",
                description=item.description,
                user_id=item.user_id,
                created_at=client_ts,
                updated_at=sync_timestamp,
                is_deleted=False,
                version=item.version or 1,
            )
            self.db.add(party)
            return True, None

        server_ts = ensure_utc(party.updated_at)
        conflict = None

        # Conflict check: did server change after client last synced?
        if last_synced_at and server_ts > last_synced_at:
            if client_ts > server_ts:
                # Client wins (LWW)
                self._apply_party_fields(party, item)
                party.updated_at = sync_timestamp
                party.version += 1
                conflict = ConflictDetail(
                    entity_type="party",
                    entity_id=party.id,
                    conflict_type="CONCURRENT_UPDATE",
                    resolution="CLIENT_APPLIED",
                    server_version=party.version - 1,
                    client_version=item.version or party.version,
                    server_timestamp=server_ts,
                    client_timestamp=client_ts,
                    message="Client offline edit is newer; applied to central database.",
                )
                return True, conflict
            else:
                # Server wins
                conflict = ConflictDetail(
                    entity_type="party",
                    entity_id=party.id,
                    conflict_type="CONCURRENT_UPDATE",
                    resolution="SERVER_PRESERVED",
                    server_version=party.version,
                    client_version=item.version or 0,
                    server_timestamp=server_ts,
                    client_timestamp=client_ts,
                    message="Central server edit is newer; preserved existing server state.",
                )
                return False, conflict

        # Normal update
        self._apply_party_fields(party, item)
        party.updated_at = sync_timestamp
        party.version += 1
        return True, None

    def _apply_party_fields(self, party: Party, item):
        if item.name is not None:
            party.name = item.name
        if item.description is not None:
            party.description = item.description
        if item.user_id is not None:
            party.user_id = item.user_id
        if item.is_deleted is not None:
            party.is_deleted = item.is_deleted

    # -------------------------------------------------------------------------
    # Hero Reconciliation
    # -------------------------------------------------------------------------

    def _reconcile_hero(self, item, last_synced_at: Optional[datetime], sync_timestamp: datetime) -> Tuple[bool, Optional[ConflictDetail]]:
        hero = self.db.query(Hero).filter(Hero.id == item.id).first()
        client_ts = ensure_utc(item.client_updated_at or item.updated_at) or sync_timestamp

        if not hero:
            if item.is_deleted:
                return False, None
            stats_dict = item.stats if isinstance(item.stats, dict) else (item.stats.model_dump() if hasattr(item.stats, "model_dump") else {"might": 0, "agility": 0, "reason": 0, "intuition": 0, "presence": 0})
            hero = Hero(
                id=item.id,
                party_id=item.party_id,
                name=item.name or "Unnamed Hero",
                ancestry=item.ancestry or "Human",
                hero_class=item.hero_class or "Fury",
                level=item.level or 1,
                stats=stats_dict,
                stamina_max=item.stamina_max if item.stamina_max is not None else 20,
                stamina_current=item.stamina_current if item.stamina_current is not None else 20,
                stamina_temp=item.stamina_temp if item.stamina_temp is not None else 0,
                recoveries_max=item.recoveries_max if item.recoveries_max is not None else 8,
                recoveries_current=item.recoveries_current if item.recoveries_current is not None else 8,
                speed=item.speed if item.speed is not None else 5,
                stability=item.stability if item.stability is not None else 0,
                victories=item.victories if item.victories is not None else 0,
                user_id=item.user_id,
                created_at=client_ts,
                updated_at=sync_timestamp,
                is_deleted=False,
                version=item.version or 1,
            )
            self.db.add(hero)
            return True, None

        server_ts = ensure_utc(hero.updated_at)
        conflict = None

        if last_synced_at and server_ts > last_synced_at:
            if client_ts > server_ts:
                # Client wins
                self._apply_hero_fields(hero, item)
                hero.updated_at = sync_timestamp
                hero.version += 1
                conflict = ConflictDetail(
                    entity_type="hero",
                    entity_id=hero.id,
                    conflict_type="CONCURRENT_UPDATE",
                    resolution="CLIENT_APPLIED",
                    server_version=hero.version - 1,
                    client_version=item.version or hero.version,
                    server_timestamp=server_ts,
                    client_timestamp=client_ts,
                    message="Client offline edit is newer; applied to central database.",
                )
                return True, conflict
            else:
                # Server wins
                conflict = ConflictDetail(
                    entity_type="hero",
                    entity_id=hero.id,
                    conflict_type="CONCURRENT_UPDATE",
                    resolution="SERVER_PRESERVED",
                    server_version=hero.version,
                    client_version=item.version or 0,
                    server_timestamp=server_ts,
                    client_timestamp=client_ts,
                    message="Central server edit is newer; preserved existing server state.",
                )
                return False, conflict

        self._apply_hero_fields(hero, item)
        hero.updated_at = sync_timestamp
        hero.version += 1
        return True, None

    def _apply_hero_fields(self, hero: Hero, item):
        if item.name is not None:
            hero.name = item.name
        if item.party_id is not None:
            hero.party_id = item.party_id
        if item.ancestry is not None:
            hero.ancestry = item.ancestry
        if item.hero_class is not None:
            hero.hero_class = item.hero_class
        if item.level is not None:
            hero.level = item.level
        if item.stats is not None:
            hero.stats = item.stats if isinstance(item.stats, dict) else (item.stats.model_dump() if hasattr(item.stats, "model_dump") else item.stats)
        if item.stamina_max is not None:
            hero.stamina_max = item.stamina_max
        if item.stamina_current is not None:
            hero.stamina_current = item.stamina_current
        if item.stamina_temp is not None:
            hero.stamina_temp = item.stamina_temp
        if item.recoveries_max is not None:
            hero.recoveries_max = item.recoveries_max
        if item.recoveries_current is not None:
            hero.recoveries_current = item.recoveries_current
        if item.speed is not None:
            hero.speed = item.speed
        if item.stability is not None:
            hero.stability = item.stability
        if item.victories is not None:
            hero.victories = item.victories
        if item.user_id is not None:
            hero.user_id = item.user_id
        if item.is_deleted is not None:
            hero.is_deleted = item.is_deleted

    # -------------------------------------------------------------------------
    # Retainer Reconciliation (Shared Party Roster)
    # -------------------------------------------------------------------------

    def _reconcile_retainer(self, item, last_synced_at: Optional[datetime], sync_timestamp: datetime) -> Tuple[bool, Optional[ConflictDetail]]:
        retainer = self.db.query(Retainer).filter(Retainer.id == item.id).first()
        client_ts = ensure_utc(item.client_updated_at or item.updated_at) or sync_timestamp

        if not retainer:
            if item.is_deleted:
                return False, None
            stats_dict = item.stats if isinstance(item.stats, dict) else (item.stats.model_dump() if hasattr(item.stats, "model_dump") else {"might": 0, "agility": 0, "reason": 0, "intuition": 0, "presence": 0})
            abilities_list = item.abilities or []
            retainer = Retainer(
                id=item.id,
                party_id=item.party_id,
                name=item.name or "Unnamed Retainer",
                retainer_type=item.retainer_type or "Soldier",
                level=item.level or 1,
                stats=stats_dict,
                stamina_max=item.stamina_max if item.stamina_max is not None else 15,
                stamina_current=item.stamina_current if item.stamina_current is not None else 15,
                stamina_temp=item.stamina_temp if item.stamina_temp is not None else 0,
                recoveries_max=item.recoveries_max if item.recoveries_max is not None else 4,
                recoveries_current=item.recoveries_current if item.recoveries_current is not None else 4,
                abilities=abilities_list,
                user_id=item.user_id,
                created_at=client_ts,
                updated_at=sync_timestamp,
                is_deleted=False,
                version=item.version or 1,
            )
            self.db.add(retainer)
            return True, None

        server_ts = ensure_utc(retainer.updated_at)
        conflict = None

        if last_synced_at and server_ts > last_synced_at:
            if client_ts > server_ts:
                # Client wins
                self._apply_retainer_fields(retainer, item)
                retainer.updated_at = sync_timestamp
                retainer.version += 1
                conflict = ConflictDetail(
                    entity_type="retainer",
                    entity_id=retainer.id,
                    conflict_type="CONCURRENT_UPDATE",
                    resolution="CLIENT_APPLIED",
                    server_version=retainer.version - 1,
                    client_version=item.version or retainer.version,
                    server_timestamp=server_ts,
                    client_timestamp=client_ts,
                    message="Client offline edit is newer; applied to central database.",
                )
                return True, conflict
            else:
                # Server wins
                conflict = ConflictDetail(
                    entity_type="retainer",
                    entity_id=retainer.id,
                    conflict_type="CONCURRENT_UPDATE",
                    resolution="SERVER_PRESERVED",
                    server_version=retainer.version,
                    client_version=item.version or 0,
                    server_timestamp=server_ts,
                    client_timestamp=client_ts,
                    message="Central server edit is newer; preserved existing server state.",
                )
                return False, conflict

        self._apply_retainer_fields(retainer, item)
        retainer.updated_at = sync_timestamp
        retainer.version += 1
        return True, None

    def _apply_retainer_fields(self, retainer: Retainer, item):
        if item.name is not None:
            retainer.name = item.name
        if item.party_id is not None:
            retainer.party_id = item.party_id
        if item.retainer_type is not None:
            retainer.retainer_type = item.retainer_type
        if item.level is not None:
            retainer.level = item.level
        if item.stats is not None:
            retainer.stats = item.stats if isinstance(item.stats, dict) else (item.stats.model_dump() if hasattr(item.stats, "model_dump") else item.stats)
        if item.stamina_max is not None:
            retainer.stamina_max = item.stamina_max
        if item.stamina_current is not None:
            retainer.stamina_current = item.stamina_current
        if item.stamina_temp is not None:
            retainer.stamina_temp = item.stamina_temp
        if item.recoveries_max is not None:
            retainer.recoveries_max = item.recoveries_max
        if item.recoveries_current is not None:
            retainer.recoveries_current = item.recoveries_current
        if item.abilities is not None:
            retainer.abilities = item.abilities
        if item.user_id is not None:
            retainer.user_id = item.user_id
        if item.is_deleted is not None:
            retainer.is_deleted = item.is_deleted

    # -------------------------------------------------------------------------
    # Assignment Reconciliation (Multi-Hero Association)
    # -------------------------------------------------------------------------

    def _reconcile_assignment(self, item, last_synced_at: Optional[datetime], sync_timestamp: datetime) -> Tuple[bool, Optional[ConflictDetail]]:
        assignment = self.db.query(HeroRetainerAssignment).filter(HeroRetainerAssignment.id == item.id).first()
        client_ts = ensure_utc(item.client_updated_at or item.updated_at) or sync_timestamp

        if not assignment:
            if item.is_deleted:
                return False, None
            if not item.hero_id or not item.retainer_id:
                return False, None

            assignment = HeroRetainerAssignment(
                id=item.id,
                hero_id=item.hero_id,
                retainer_id=item.retainer_id,
                session_id=item.session_id,
                role_description=item.role_description,
                active=item.active if item.active is not None else True,
                assigned_at=client_ts,
                created_at=client_ts,
                updated_at=sync_timestamp,
                is_deleted=False,
                version=item.version or 1,
            )
            self.db.add(assignment)
            return True, None

        server_ts = ensure_utc(assignment.updated_at)
        conflict = None

        if last_synced_at and server_ts > last_synced_at:
            if client_ts > server_ts:
                # Client wins
                self._apply_assignment_fields(assignment, item)
                assignment.updated_at = sync_timestamp
                assignment.version += 1
                conflict = ConflictDetail(
                    entity_type="assignment",
                    entity_id=assignment.id,
                    conflict_type="CONCURRENT_UPDATE",
                    resolution="CLIENT_APPLIED",
                    server_version=assignment.version - 1,
                    client_version=item.version or assignment.version,
                    server_timestamp=server_ts,
                    client_timestamp=client_ts,
                    message="Client offline edit is newer; applied to central database.",
                )
                return True, conflict
            else:
                # Server wins
                conflict = ConflictDetail(
                    entity_type="assignment",
                    entity_id=assignment.id,
                    conflict_type="CONCURRENT_UPDATE",
                    resolution="SERVER_PRESERVED",
                    server_version=assignment.version,
                    client_version=item.version or 0,
                    server_timestamp=server_ts,
                    client_timestamp=client_ts,
                    message="Central server edit is newer; preserved existing server state.",
                )
                return False, conflict

        self._apply_assignment_fields(assignment, item)
        assignment.updated_at = sync_timestamp
        assignment.version += 1
        return True, None

    def _apply_assignment_fields(self, assignment: HeroRetainerAssignment, item):
        if item.hero_id is not None:
            assignment.hero_id = item.hero_id
        if item.retainer_id is not None:
            assignment.retainer_id = item.retainer_id
        if item.session_id is not None:
            assignment.session_id = item.session_id
        if item.role_description is not None:
            assignment.role_description = item.role_description
        if item.active is not None:
            assignment.active = item.active
        if item.is_deleted is not None:
            assignment.is_deleted = item.is_deleted

    # -------------------------------------------------------------------------
    # Gather Server Changes
    # -------------------------------------------------------------------------

    def _gather_server_changes(self, last_synced_at: Optional[datetime]) -> SyncServerChanges:
        def filter_since(query_cls):
            q = self.db.query(query_cls)
            if last_synced_at:
                q = q.filter(query_cls.updated_at > last_synced_at)
            return q.all()

        server_parties = filter_since(Party)
        server_heroes = filter_since(Hero)
        server_retainers = filter_since(Retainer)
        server_assignments = filter_since(HeroRetainerAssignment)

        return SyncServerChanges(
            parties=[PartyResponse.model_validate(p) for p in server_parties],
            heroes=[HeroResponse.model_validate(h) for h in server_heroes],
            retainers=[RetainerResponse.model_validate(r) for r in server_retainers],
            assignments=[HeroRetainerAssignmentResponse.model_validate(a) for a in server_assignments],
        )
