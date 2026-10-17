"""Tests for Forge Steel central hero and retainer database extension.

Verifies:
1. Shared party roster for retainers
2. Multi-hero association (one retainer accompanying multiple heroes)
3. Retainer independent stats, stamina tracking, and Draw Steel abilities
4. Bidirectional offline sync protocol
5. Conflict resolution (Client-Wins vs Server-Wins Last-Write-Wins policies)
6. Soft delete propagation
"""

import os
import uuid
import pytest
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from sqlalchemy.pool import StaticPool

from database import Base, get_db
from server import app
from models import (
    Party,
    Hero,
    Retainer,
    HeroRetainerAssignment,
    utc_now,
)

# Test Database setup (isolated SQLite in-memory database with shared connection pool)
TEST_DATABASE_URL = "sqlite:///:memory:"
test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
def setup_test_db():
    """Create fresh database tables before each test and drop after."""
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture
def client():
    """FastAPI TestClient fixture."""
    return TestClient(app)


# ============================================================================
# Test 1: Party and Shared Retainers Roster
# ============================================================================


def test_party_and_shared_retainers_roster(client):
    """Retainers must belong to a shared party roster rather than locked to a hero."""
    # 1. Create Party
    party_res = client.post("/api/parties", json={"name": "The Steel Vanguard", "description": "Draw Steel adventuring company"})
    assert party_res.status_code == 201
    party_id = party_res.json()["id"]

    # 2. Create Heroes in Party
    hero1_res = client.post(
        "/api/heroes",
        json={
            "name": "Sir Gareth",
            "party_id": party_id,
            "hero_class": "Fury",
            "ancestry": "Human",
            "level": 2,
            "stats": {"might": 2, "agility": 1, "reason": 0, "intuition": 0, "presence": 0},
            "stamina_max": 24,
            "stamina_current": 24,
        },
    )
    assert hero1_res.status_code == 201

    hero2_res = client.post(
        "/api/heroes",
        json={
            "name": "Morrigan",
            "party_id": party_id,
            "hero_class": "Shadow",
            "ancestry": "Wode Elf",
            "level": 2,
            "stats": {"might": 0, "agility": 2, "reason": 1, "intuition": 1, "presence": -1},
            "stamina_max": 20,
            "stamina_current": 20,
        },
    )
    assert hero2_res.status_code == 201

    # 3. Create Retainer in Shared Party Roster
    retainer_res = client.post(
        "/api/retainers",
        json={
            "name": "Barris the Shield",
            "party_id": party_id,
            "retainer_type": "Soldier",
            "level": 1,
            "stats": {"might": 2, "agility": 0, "reason": 0, "intuition": 1, "presence": 0},
            "stamina_max": 18,
            "stamina_current": 18,
            "stamina_temp": 0,
            "recoveries_max": 4,
            "recoveries_current": 4,
            "abilities": [
                {
                    "name": "Shield Slam",
                    "type": "action",
                    "distance": "Melee 1",
                    "roll_bonus": 2,
                    "tier_1": "3 damage",
                    "tier_2": "6 damage",
                    "tier_3": "9 damage + target prone",
                }
            ],
        },
    )
    assert retainer_res.status_code == 201
    retainer_id = retainer_res.json()["id"]

    # 4. Check Party Roster composite endpoint
    roster_res = client.get(f"/api/parties/{party_id}/roster")
    assert roster_res.status_code == 200
    roster_data = roster_res.json()

    assert len(roster_data["heroes"]) == 2
    assert len(roster_data["shared_retainers"]) == 1
    assert roster_data["shared_retainers"][0]["id"] == retainer_id
    assert roster_data["shared_retainers"][0]["name"] == "Barris the Shield"


# ============================================================================
# Test 2: Multi-Hero Association (One Retainer Accompanying Multiple Heroes)
# ============================================================================


def test_shared_retainer_multi_hero_association(client):
    """One retainer can accompany multiple heroes across sessions or concurrently without duplicating."""
    # Create Party
    party_res = client.post("/api/parties", json={"name": "Ironbound Freeblades"})
    party_id = party_res.json()["id"]

    # Create Hero 1 and Hero 2
    hero1_id = client.post("/api/heroes", json={"name": "Kaelen", "party_id": party_id}).json()["id"]
    hero2_id = client.post("/api/heroes", json={"name": "Lyra", "party_id": party_id}).json()["id"]

    # Create Retainer
    retainer_id = client.post(
        "/api/retainers",
        json={"name": "Finnegan the Scout", "party_id": party_id, "retainer_type": "Scout"},
    ).json()["id"]

    # Initially, neither hero has retainers assigned
    assert len(client.get(f"/api/heroes/{hero1_id}/retainers").json()) == 0
    assert len(client.get(f"/api/heroes/{hero2_id}/retainers").json()) == 0

    # Assign Finnegan to Kaelen for Session 1
    assign1_res = client.post(
        "/api/assignments",
        json={
            "hero_id": hero1_id,
            "retainer_id": retainer_id,
            "session_id": "session_01",
            "role_description": "Vanguard Scout",
        },
    )
    assert assign1_res.status_code == 201

    # Assign SAME Finnegan to Lyra for Session 2
    assign2_res = client.post(
        "/api/assignments",
        json={
            "hero_id": hero2_id,
            "retainer_id": retainer_id,
            "session_id": "session_02",
            "role_description": "Flanking Specialist",
        },
    )
    assert assign2_res.status_code == 201

    # Check Hero 1 retainers
    h1_retainers = client.get(f"/api/heroes/{hero1_id}/retainers").json()
    assert len(h1_retainers) == 1
    assert h1_retainers[0]["id"] == retainer_id

    # Check Hero 2 retainers
    h2_retainers = client.get(f"/api/heroes/{hero2_id}/retainers").json()
    assert len(h2_retainers) == 1
    assert h2_retainers[0]["id"] == retainer_id

    # Query reverse association: Which heroes does Finnegan accompany?
    heroes_for_finnegan = client.get(f"/api/retainers/{retainer_id}/heroes").json()
    assert len(heroes_for_finnegan) == 2
    returned_hero_ids = {h["id"] for h in heroes_for_finnegan}
    assert returned_hero_ids == {hero1_id, hero2_id}


# ============================================================================
# Test 3: Retainer Stats, Stamina, and Abilities Tracking
# ============================================================================


def test_retainer_stats_stamina_and_abilities(client):
    """Retainer has independent stats, stamina tracking, and Draw Steel abilities."""
    create_res = client.post(
        "/api/retainers",
        json={
            "name": "Sister Althea",
            "retainer_type": "Priest",
            "level": 1,
            "stats": {"might": 0, "agility": 0, "reason": 1, "intuition": 2, "presence": 1},
            "stamina_max": 16,
            "stamina_current": 16,
            "stamina_temp": 0,
            "recoveries_max": 4,
            "recoveries_current": 4,
            "abilities": [
                {
                    "name": "Word of Radiance",
                    "type": "action",
                    "distance": "Ranged 5",
                    "roll_bonus": 2,
                    "tier_1": "3 holy damage",
                    "tier_2": "6 holy damage",
                    "tier_3": "9 holy damage + ally gains 3 stamina",
                }
            ],
        },
    )
    assert create_res.status_code == 201
    retainer_id = create_res.json()["id"]

    # Althea takes 6 damage, gains 4 temporary stamina, and spends 1 recovery
    update_res = client.put(
        f"/api/retainers/{retainer_id}",
        json={
            "stamina_current": 10,
            "stamina_temp": 4,
            "recoveries_current": 3,
            "abilities": [
                {
                    "name": "Word of Radiance",
                    "type": "action",
                    "distance": "Ranged 5",
                    "roll_bonus": 2,
                    "tier_1": "3 holy damage",
                    "tier_2": "6 holy damage",
                    "tier_3": "9 holy damage + ally gains 3 stamina",
                },
                {
                    "name": "Healing Touch",
                    "type": "maneuver",
                    "distance": "Melee 1",
                    "description": "Target ally spends a recovery to regain stamina.",
                },
            ],
        },
    )
    assert update_res.status_code == 200
    data = update_res.json()
    assert data["stamina_current"] == 10
    assert data["stamina_temp"] == 4
    assert data["recoveries_current"] == 3
    assert len(data["abilities"]) == 2
    assert data["abilities"][1]["name"] == "Healing Touch"


# ============================================================================
# Test 4: Offline Sync - Initial Push from Client Cache
# ============================================================================


def test_offline_sync_initial_push(client):
    """Client creates entities offline in IndexedDB and pushes them to central database."""
    party_id = str(uuid.uuid4())
    hero_id = str(uuid.uuid4())
    retainer_id = str(uuid.uuid4())
    assignment_id = str(uuid.uuid4())

    now = utc_now()

    sync_payload = {
        "client_id": "browser_client_owen_mac",
        "last_synced_at": None,
        "changes": {
            "parties": [{"id": party_id, "name": "Offline Party", "updated_at": now.isoformat()}],
            "heroes": [
                {
                    "id": hero_id,
                    "party_id": party_id,
                    "name": "Offline Hero",
                    "hero_class": "Tactician",
                    "updated_at": now.isoformat(),
                }
            ],
            "retainers": [
                {
                    "id": retainer_id,
                    "party_id": party_id,
                    "name": "Offline Retainer",
                    "retainer_type": "Mage",
                    "updated_at": now.isoformat(),
                }
            ],
            "assignments": [
                {
                    "id": assignment_id,
                    "hero_id": hero_id,
                    "retainer_id": retainer_id,
                    "session_id": "session_alpha",
                    "updated_at": now.isoformat(),
                }
            ],
        },
    }

    res = client.post("/api/sync", json=sync_payload)
    assert res.status_code == 200
    data = res.json()

    assert data["applied_count"] == 4
    assert len(data["conflicts"]) == 0
    assert data["sync_timestamp"] is not None

    # Verify central database now has these entities
    p = client.get(f"/api/parties/{party_id}")
    assert p.status_code == 200
    assert p.json()["name"] == "Offline Party"

    h = client.get(f"/api/heroes/{hero_id}")
    assert h.status_code == 200
    assert h.json()["name"] == "Offline Hero"

    r = client.get(f"/api/retainers/{retainer_id}")
    assert r.status_code == 200
    assert r.json()["name"] == "Offline Retainer"

    h_retainers = client.get(f"/api/heroes/{hero_id}/retainers")
    assert len(h_retainers.json()) == 1


# ============================================================================
# Test 5: Offline Sync - Incremental Pull of Server Changes
# ============================================================================


def test_offline_sync_incremental_pull(client):
    """Client with an existing last_synced_at timestamp pulls newer server changes."""
    t0 = utc_now() - timedelta(minutes=10)

    # Server creates hero after t0
    hero_res = client.post("/api/heroes", json={"name": "Server Created Hero", "hero_class": "Conduit"})
    hero_id = hero_res.json()["id"]

    # Client syncs with last_synced_at = t0
    res = client.post(
        "/api/sync",
        json={
            "client_id": "browser_client_node_b",
            "last_synced_at": t0.isoformat(),
            "changes": {"parties": [], "heroes": [], "retainers": [], "assignments": []},
        },
    )
    assert res.status_code == 200
    data = res.json()

    # The hero created on the server should be in server_changes
    pulled_heroes = [h for h in data["server_changes"]["heroes"] if h["id"] == hero_id]
    assert len(pulled_heroes) == 1
    assert pulled_heroes[0]["name"] == "Server Created Hero"


# ============================================================================
# Test 6: Offline Sync - Conflict Resolution (Client Wins when Newer)
# ============================================================================


def test_offline_sync_conflict_resolution_client_wins(client):
    """When client offline edit is newer than server edit, client edit is applied."""
    t0 = utc_now() - timedelta(hours=2)

    # 1. Entity created at t0
    hero_res = client.post("/api/heroes", json={"name": "Kaelen Original", "level": 1})
    hero_id = hero_res.json()["id"]

    # 2. Server modified entity at t1
    client.put(f"/api/heroes/{hero_id}", json={"name": "Kaelen Server Edit", "level": 2})

    # 3. Client modified entity offline at t2 (newer than server edit)
    t2 = utc_now() + timedelta(minutes=5)

    sync_res = client.post(
        "/api/sync",
        json={
            "client_id": "client_laptop",
            "last_synced_at": t0.isoformat(),
            "changes": {
                "heroes": [
                    {
                        "id": hero_id,
                        "name": "Kaelen Offline Client Edit",
                        "level": 3,
                        "client_updated_at": t2.isoformat(),
                    }
                ]
            },
        },
    )
    assert sync_res.status_code == 200
    data = sync_res.json()

    assert data["applied_count"] == 1
    assert len(data["conflicts"]) == 1
    assert data["conflicts"][0]["resolution"] == "CLIENT_APPLIED"
    assert data["conflicts"][0]["entity_id"] == hero_id

    # Central DB should reflect client's edit
    updated_hero = client.get(f"/api/heroes/{hero_id}").json()
    assert updated_hero["name"] == "Kaelen Offline Client Edit"
    assert updated_hero["level"] == 3


# ============================================================================
# Test 7: Offline Sync - Conflict Resolution (Server Wins when Newer)
# ============================================================================


def test_offline_sync_conflict_resolution_server_wins(client):
    """When server edit is newer than client offline edit, server preserves state."""
    t0 = utc_now() - timedelta(hours=3)
    t1_client = utc_now() - timedelta(hours=2)

    # 1. Entity created
    hero_res = client.post("/api/heroes", json={"name": "Aria Original", "level": 1})
    hero_id = hero_res.json()["id"]

    # 2. Server receives fresh update now (t_server > t1_client)
    client.put(f"/api/heroes/{hero_id}", json={"name": "Aria Authoritative Server", "level": 5})

    # 3. Client attempts to push older offline edit
    sync_res = client.post(
        "/api/sync",
        json={
            "client_id": "client_phone",
            "last_synced_at": t0.isoformat(),
            "changes": {
                "heroes": [
                    {
                        "id": hero_id,
                        "name": "Aria Stale Offline Edit",
                        "level": 2,
                        "client_updated_at": t1_client.isoformat(),
                    }
                ]
            },
        },
    )
    assert sync_res.status_code == 200
    data = sync_res.json()

    assert data["applied_count"] == 0
    assert len(data["conflicts"]) == 1
    assert data["conflicts"][0]["resolution"] == "SERVER_PRESERVED"
    assert data["conflicts"][0]["entity_id"] == hero_id

    # Server state should remain unchanged
    current_hero = client.get(f"/api/heroes/{hero_id}").json()
    assert current_hero["name"] == "Aria Authoritative Server"
    assert current_hero["level"] == 5

    # Server changes sent to client should contain server version
    matching = [h for h in data["server_changes"]["heroes"] if h["id"] == hero_id]
    assert len(matching) == 1
    assert matching[0]["name"] == "Aria Authoritative Server"


# ============================================================================
# Test 8: Offline Sync - Soft Delete Propagation (Tombstones)
# ============================================================================


def test_offline_sync_soft_delete_propagation(client):
    """Soft-deleted entities propagate as tombstones (is_deleted=True) to offline clients."""
    # Create Retainer
    retainer_res = client.post("/api/retainers", json={"name": "Temp Retainer", "retainer_type": "Scout"})
    retainer_id = retainer_res.json()["id"]

    # Delete Retainer via server API
    del_res = client.delete(f"/api/retainers/{retainer_id}")
    assert del_res.status_code == 204

    # Client syncs since beginning of time
    sync_res = client.post(
        "/api/sync",
        json={
            "client_id": "client_mac",
            "last_synced_at": None,
            "changes": {},
        },
    )
    assert sync_res.status_code == 200
    data = sync_res.json()

    # The deleted retainer should be included with is_deleted=True so client knows to remove it
    deleted_matches = [r for r in data["server_changes"]["retainers"] if r["id"] == retainer_id]
    assert len(deleted_matches) == 1
    assert deleted_matches[0]["is_deleted"] is True


# ============================================================================
# Test 9: Assignment Lifecycle and Unassignment
# ============================================================================


def test_assignment_lifecycle_and_unassign(client):
    """Assignments can be removed/deactivated without deleting the shared retainer."""
    party_id = client.post("/api/parties", json={"name": "Solo Party"}).json()["id"]
    hero_id = client.post("/api/heroes", json={"name": "Thorin", "party_id": party_id}).json()["id"]
    retainer_id = client.post("/api/retainers", json={"name": "Balin", "party_id": party_id}).json()["id"]

    # Assign
    assign_res = client.post(
        "/api/assignments",
        json={"hero_id": hero_id, "retainer_id": retainer_id, "session_id": "session_01"},
    )
    assert assign_res.status_code == 201
    assignment_id = assign_res.json()["id"]

    # Verify hero has retainer
    assert len(client.get(f"/api/heroes/{hero_id}/retainers").json()) == 1

    # Unassign
    del_res = client.delete(f"/api/assignments/{assignment_id}")
    assert del_res.status_code == 204

    # Verify hero no longer has retainer
    assert len(client.get(f"/api/heroes/{hero_id}/retainers").json()) == 0

    # Retainer STILL exists in the party roster
    r = client.get(f"/api/retainers/{retainer_id}")
    assert r.status_code == 200
    assert r.json()["name"] == "Balin"


# ============================================================================
# Test 10: Multi-Retainer Assignments & Complex Roster Linking
# ============================================================================


def test_multi_retainers_per_hero_and_party_sharing(client):
    """Heroes can have multiple retainers, and retainers can be shared across heroes concurrently."""
    party_id = client.post("/api/parties", json={"name": "Expeditionary Force"}).json()["id"]

    hero1_id = client.post("/api/heroes", json={"name": "Valen", "party_id": party_id}).json()["id"]
    hero2_id = client.post("/api/heroes", json={"name": "Cora", "party_id": party_id}).json()["id"]

    ret1_id = client.post("/api/retainers", json={"name": "Shield Retainer", "party_id": party_id}).json()["id"]
    ret2_id = client.post("/api/retainers", json={"name": "Healer Retainer", "party_id": party_id}).json()["id"]

    # Assign ret1 to hero1 and ret2 to hero1 (hero1 has 2 retainers)
    client.post("/api/assignments", json={"hero_id": hero1_id, "retainer_id": ret1_id})
    client.post("/api/assignments", json={"hero_id": hero1_id, "retainer_id": ret2_id})

    # Also assign ret2 to hero2 (ret2 shared between hero1 and hero2)
    client.post("/api/assignments", json={"hero_id": hero2_id, "retainer_id": ret2_id})

    # Verify hero1 has both ret1 and ret2
    h1_rets = client.get(f"/api/heroes/{hero1_id}/retainers").json()
    assert len(h1_rets) == 2
    assert {r["id"] for r in h1_rets} == {ret1_id, ret2_id}

    # Verify hero2 has ret2
    h2_rets = client.get(f"/api/heroes/{hero2_id}/retainers").json()
    assert len(h2_rets) == 1
    assert h2_rets[0]["id"] == ret2_id

    # Verify ret2 has both heroes
    ret2_heroes = client.get(f"/api/retainers/{ret2_id}/heroes").json()
    assert len(ret2_heroes) == 2
    assert {h["id"] for h in ret2_heroes} == {hero1_id, hero2_id}


# ============================================================================
# Test 11: Offline Sync Idempotency
# ============================================================================


def test_offline_sync_idempotency(client):
    """Submitting the same sync batch multiple times produces idempotent, deterministic results."""
    party_id = str(uuid.uuid4())
    hero_id = str(uuid.uuid4())
    t = utc_now().isoformat()

    payload = {
        "client_id": "client_idempotent",
        "last_synced_at": None,
        "changes": {
            "parties": [{"id": party_id, "name": "Idempotent Party", "updated_at": t}],
            "heroes": [{"id": hero_id, "party_id": party_id, "name": "Idempotent Hero", "updated_at": t}],
        },
    }

    res1 = client.post("/api/sync", json=payload)
    assert res1.status_code == 200
    assert res1.json()["applied_count"] == 2

    # Resend identical payload with last_synced_at set to timestamp from first sync
    t_sync = res1.json()["sync_timestamp"]
    payload["last_synced_at"] = t_sync

    res2 = client.post("/api/sync", json=payload)
    assert res2.status_code == 200
    # No new conflicts, entities exist cleanly
    assert len(res2.json()["conflicts"]) == 0

    # Ensure no duplicates were created
    parties = client.get("/api/parties").json()
    matching_parties = [p for p in parties if p["id"] == party_id]
    assert len(matching_parties) == 1


# ============================================================================
# Test 12: Assignment Invalid References Handling
# ============================================================================


def test_assignment_invalid_references(client):
    """Attempting to assign a non-existent hero or retainer returns 404."""
    real_hero_id = client.post("/api/heroes", json={"name": "Real Hero"}).json()["id"]

    res = client.post(
        "/api/assignments",
        json={"hero_id": real_hero_id, "retainer_id": "non-existent-retainer-id"},
    )
    assert res.status_code == 404
    assert "Retainer not found" in res.json()["detail"]

    res2 = client.post(
        "/api/assignments",
        json={"hero_id": "non-existent-hero-id", "retainer_id": "something"},
    )
    assert res2.status_code == 404
    assert "Hero not found" in res2.json()["detail"]

