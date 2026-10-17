"""Data models for Forge Steel central hero and retainer database.

Implements SQLAlchemy ORM models and Pydantic validation schemas.
Supports shared party retainers, multi-hero association, Draw Steel stats,
stamina/recovery tracking, abilities, and offline synchronization metadata.
"""

from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey, JSON, Text
from sqlalchemy.orm import relationship
from pydantic import BaseModel, Field, ConfigDict

from database import Base


def utc_now() -> datetime:
    """Return timezone-aware current UTC datetime."""
    return datetime.now(timezone.utc)


def generate_uuid() -> str:
    """Generate string UUID."""
    return str(uuid.uuid4())


# ============================================================================
# SQLAlchemy ORM Models
# ============================================================================


class Party(Base):
    """Party model representing an adventuring party.
    
    A party contains a shared roster of heroes and retainers. Retainers belong
    to the party roster and can be assigned to multiple heroes across sessions.
    """
    __tablename__ = "parties"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    user_id = Column(String(255), nullable=True, index=True)

    # Sync and audit fields
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False, index=True)
    is_deleted = Column(Boolean, default=False, nullable=False, index=True)
    version = Column(Integer, default=1, nullable=False)

    # Relationships
    heroes = relationship(
        "Hero",
        back_populates="party",
        foreign_keys="Hero.party_id"
    )
    retainers = relationship(
        "Retainer",
        back_populates="party",
        foreign_keys="Retainer.party_id"
    )


class Hero(Base):
    """Draw Steel Hero model.
    
    Heroes belong to a party and can have multiple retainers assigned to them.
    """
    __tablename__ = "heroes"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    party_id = Column(String(36), ForeignKey("parties.id", ondelete="SET NULL"), nullable=True, index=True)
    name = Column(String(255), nullable=False)
    ancestry = Column(String(100), default="Human", nullable=False)
    hero_class = Column(String(100), default="Fury", nullable=False)
    level = Column(Integer, default=1, nullable=False)

    # Draw Steel Core Characteristics (Might, Agility, Reason, Intuition, Presence)
    stats = Column(JSON, default=lambda: {"might": 0, "agility": 0, "reason": 0, "intuition": 0, "presence": 0}, nullable=False)

    # Combat attributes
    stamina_max = Column(Integer, default=20, nullable=False)
    stamina_current = Column(Integer, default=20, nullable=False)
    stamina_temp = Column(Integer, default=0, nullable=False)
    recoveries_max = Column(Integer, default=8, nullable=False)
    recoveries_current = Column(Integer, default=8, nullable=False)
    speed = Column(Integer, default=5, nullable=False)
    stability = Column(Integer, default=0, nullable=False)
    victories = Column(Integer, default=0, nullable=False)

    user_id = Column(String(255), nullable=True, index=True)

    # Sync and audit fields
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False, index=True)
    is_deleted = Column(Boolean, default=False, nullable=False, index=True)
    version = Column(Integer, default=1, nullable=False)

    # Relationships
    party = relationship("Party", back_populates="heroes")
    retainer_assignments = relationship(
        "HeroRetainerAssignment",
        back_populates="hero",
        cascade="all, delete-orphan",
        foreign_keys="HeroRetainerAssignment.hero_id"
    )


class Retainer(Base):
    """Draw Steel Retainer model.
    
    Retainers belong to a central party roster rather than being locked to a single hero.
    One retainer can accompany multiple heroes across different sessions or simultaneously.
    Has full stat block, independent stamina tracking, recovery counter, and attack abilities.
    """
    __tablename__ = "retainers"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    party_id = Column(String(36), ForeignKey("parties.id", ondelete="SET NULL"), nullable=True, index=True)
    name = Column(String(255), nullable=False)
    retainer_type = Column(String(100), default="Soldier", nullable=False)  # Soldier, Scout, Sage, Priest, Mage, etc.
    level = Column(Integer, default=1, nullable=False)

    # Characteristics (Might, Agility, Reason, Intuition, Presence)
    stats = Column(JSON, default=lambda: {"might": 0, "agility": 0, "reason": 0, "intuition": 0, "presence": 0}, nullable=False)

    # Independent stamina & recovery tracking
    stamina_max = Column(Integer, default=15, nullable=False)
    stamina_current = Column(Integer, default=15, nullable=False)
    stamina_temp = Column(Integer, default=0, nullable=False)
    recoveries_max = Column(Integer, default=4, nullable=False)
    recoveries_current = Column(Integer, default=4, nullable=False)

    # Attack abilities, maneuvers, free strikes, and signature features
    abilities = Column(JSON, default=list, nullable=False)

    user_id = Column(String(255), nullable=True, index=True)

    # Sync and audit fields
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False, index=True)
    is_deleted = Column(Boolean, default=False, nullable=False, index=True)
    version = Column(Integer, default=1, nullable=False)

    # Relationships
    party = relationship("Party", back_populates="retainers")
    hero_assignments = relationship(
        "HeroRetainerAssignment",
        back_populates="retainer",
        cascade="all, delete-orphan",
        foreign_keys="HeroRetainerAssignment.retainer_id"
    )


class HeroRetainerAssignment(Base):
    """Many-to-Many association tracking retainer companionship with heroes.
    
    Allows a retainer to accompany Hero A in Session 1, Hero B in Session 2,
    or multiple heroes concurrently without duplicating the retainer's sheet.
    """
    __tablename__ = "hero_retainer_assignments"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    hero_id = Column(String(36), ForeignKey("heroes.id", ondelete="CASCADE"), nullable=False, index=True)
    retainer_id = Column(String(36), ForeignKey("retainers.id", ondelete="CASCADE"), nullable=False, index=True)
    session_id = Column(String(100), nullable=True, index=True)
    role_description = Column(String(255), nullable=True)  # e.g. "Bodyguard", "Vanguard", "Field Medic"
    active = Column(Boolean, default=True, nullable=False)

    # Sync and audit fields
    assigned_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False, index=True)
    is_deleted = Column(Boolean, default=False, nullable=False, index=True)
    version = Column(Integer, default=1, nullable=False)

    # Relationships
    hero = relationship("Hero", back_populates="retainer_assignments")
    retainer = relationship("Retainer", back_populates="hero_assignments")


# ============================================================================
# Pydantic Schemas
# ============================================================================


class StatsSchema(BaseModel):
    """Draw Steel characteristics schema."""
    might: int = Field(default=0, description="Might characteristic modifier")
    agility: int = Field(default=0, description="Agility characteristic modifier")
    reason: int = Field(default=0, description="Reason characteristic modifier")
    intuition: int = Field(default=0, description="Intuition characteristic modifier")
    presence: int = Field(default=0, description="Presence characteristic modifier")

    model_config = ConfigDict(from_attributes=True)


class AbilitySchema(BaseModel):
    """Draw Steel ability or attack roll schema."""
    id: Optional[str] = None
    name: str
    type: str = "action"  # action, maneuver, trigger, free_strike, feature
    distance: Optional[str] = "Melee 1"
    target: Optional[str] = "1 creature"
    characteristic: Optional[str] = "might"
    roll_bonus: int = 0
    tier_1: Optional[str] = None  # Roll result <= 11
    tier_2: Optional[str] = None  # Roll result 12-16
    tier_3: Optional[str] = None  # Roll result 17+
    description: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# --- Party Schemas ---


class PartyBase(BaseModel):
    name: str
    description: Optional[str] = None
    user_id: Optional[str] = None


class PartyCreate(PartyBase):
    id: Optional[str] = None


class PartyUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    user_id: Optional[str] = None
    is_deleted: Optional[bool] = None


class PartyResponse(PartyBase):
    id: str
    created_at: datetime
    updated_at: datetime
    is_deleted: bool
    version: int

    model_config = ConfigDict(from_attributes=True)


# --- Hero Schemas ---


class HeroBase(BaseModel):
    name: str
    party_id: Optional[str] = None
    ancestry: str = "Human"
    hero_class: str = "Fury"
    level: int = 1
    stats: StatsSchema = Field(default_factory=StatsSchema)
    stamina_max: int = 20
    stamina_current: int = 20
    stamina_temp: int = 0
    recoveries_max: int = 8
    recoveries_current: int = 8
    speed: int = 5
    stability: int = 0
    victories: int = 0
    user_id: Optional[str] = None


class HeroCreate(HeroBase):
    id: Optional[str] = None


class HeroUpdate(BaseModel):
    name: Optional[str] = None
    party_id: Optional[str] = None
    ancestry: Optional[str] = None
    hero_class: Optional[str] = None
    level: Optional[int] = None
    stats: Optional[StatsSchema] = None
    stamina_max: Optional[int] = None
    stamina_current: Optional[int] = None
    stamina_temp: Optional[int] = None
    recoveries_max: Optional[int] = None
    recoveries_current: Optional[int] = None
    speed: Optional[int] = None
    stability: Optional[int] = None
    victories: Optional[int] = None
    user_id: Optional[str] = None
    is_deleted: Optional[bool] = None


class HeroResponse(HeroBase):
    id: str
    created_at: datetime
    updated_at: datetime
    is_deleted: bool
    version: int

    model_config = ConfigDict(from_attributes=True)


# --- Retainer Schemas ---


class RetainerBase(BaseModel):
    name: str
    party_id: Optional[str] = None
    retainer_type: str = "Soldier"
    level: int = 1
    stats: StatsSchema = Field(default_factory=StatsSchema)
    stamina_max: int = 15
    stamina_current: int = 15
    stamina_temp: int = 0
    recoveries_max: int = 4
    recoveries_current: int = 4
    abilities: List[AbilitySchema] = Field(default_factory=list)
    user_id: Optional[str] = None


class RetainerCreate(RetainerBase):
    id: Optional[str] = None


class RetainerUpdate(BaseModel):
    name: Optional[str] = None
    party_id: Optional[str] = None
    retainer_type: Optional[str] = None
    level: Optional[int] = None
    stats: Optional[StatsSchema] = None
    stamina_max: Optional[int] = None
    stamina_current: Optional[int] = None
    stamina_temp: Optional[int] = None
    recoveries_max: Optional[int] = None
    recoveries_current: Optional[int] = None
    abilities: Optional[List[AbilitySchema]] = None
    user_id: Optional[str] = None
    is_deleted: Optional[bool] = None


class RetainerResponse(RetainerBase):
    id: str
    created_at: datetime
    updated_at: datetime
    is_deleted: bool
    version: int

    model_config = ConfigDict(from_attributes=True)


# --- Assignment Schemas ---


class HeroRetainerAssignmentCreate(BaseModel):
    id: Optional[str] = None
    hero_id: str
    retainer_id: str
    session_id: Optional[str] = None
    role_description: Optional[str] = None
    active: bool = True


class HeroRetainerAssignmentResponse(BaseModel):
    id: str
    hero_id: str
    retainer_id: str
    session_id: Optional[str] = None
    role_description: Optional[str] = None
    active: bool
    assigned_at: datetime
    created_at: datetime
    updated_at: datetime
    is_deleted: bool
    version: int

    model_config = ConfigDict(from_attributes=True)


# --- Party Roster Composite Response ---


class PartyRosterResponse(BaseModel):
    party: PartyResponse
    heroes: List[HeroResponse]
    shared_retainers: List[RetainerResponse]
    assignments: List[HeroRetainerAssignmentResponse]

    model_config = ConfigDict(from_attributes=True)


# --- Sync Schemas ---


class SyncItem(BaseModel):
    """Base schema for items submitted in sync requests from browser caches."""
    id: str
    updated_at: Optional[datetime] = None
    client_updated_at: Optional[datetime] = None
    is_deleted: bool = False
    version: Optional[int] = 1


class PartySyncItem(SyncItem):
    name: Optional[str] = None
    description: Optional[str] = None
    user_id: Optional[str] = None


class HeroSyncItem(SyncItem):
    party_id: Optional[str] = None
    name: Optional[str] = None
    ancestry: Optional[str] = None
    hero_class: Optional[str] = None
    level: Optional[int] = None
    stats: Optional[Dict[str, Any]] = None
    stamina_max: Optional[int] = None
    stamina_current: Optional[int] = None
    stamina_temp: Optional[int] = None
    recoveries_max: Optional[int] = None
    recoveries_current: Optional[int] = None
    speed: Optional[int] = None
    stability: Optional[int] = None
    victories: Optional[int] = None
    user_id: Optional[str] = None


class RetainerSyncItem(SyncItem):
    party_id: Optional[str] = None
    name: Optional[str] = None
    retainer_type: Optional[str] = None
    level: Optional[int] = None
    stats: Optional[Dict[str, Any]] = None
    stamina_max: Optional[int] = None
    stamina_current: Optional[int] = None
    stamina_temp: Optional[int] = None
    recoveries_max: Optional[int] = None
    recoveries_current: Optional[int] = None
    abilities: Optional[List[Dict[str, Any]]] = None
    user_id: Optional[str] = None


class AssignmentSyncItem(SyncItem):
    hero_id: Optional[str] = None
    retainer_id: Optional[str] = None
    session_id: Optional[str] = None
    role_description: Optional[str] = None
    active: Optional[bool] = None


class SyncChanges(BaseModel):
    parties: List[PartySyncItem] = Field(default_factory=list)
    heroes: List[HeroSyncItem] = Field(default_factory=list)
    retainers: List[RetainerSyncItem] = Field(default_factory=list)
    assignments: List[AssignmentSyncItem] = Field(default_factory=list)


class SyncServerChanges(BaseModel):
    parties: List[PartyResponse] = Field(default_factory=list)
    heroes: List[HeroResponse] = Field(default_factory=list)
    retainers: List[RetainerResponse] = Field(default_factory=list)
    assignments: List[HeroRetainerAssignmentResponse] = Field(default_factory=list)


class ConflictDetail(BaseModel):
    entity_type: str
    entity_id: str
    conflict_type: str  # e.g., "CONCURRENT_UPDATE", "UPDATE_DELETE", "DELETE_UPDATE"
    resolution: str     # e.g., "CLIENT_APPLIED", "SERVER_PRESERVED"
    server_version: int
    client_version: int
    server_timestamp: Optional[datetime] = None
    client_timestamp: Optional[datetime] = None
    message: str


class SyncRequest(BaseModel):
    client_id: str
    last_synced_at: Optional[datetime] = None
    changes: SyncChanges = Field(default_factory=SyncChanges)


class SyncResponse(BaseModel):
    sync_timestamp: datetime
    applied_count: int
    conflicts: List[ConflictDetail] = Field(default_factory=list)
    server_changes: SyncServerChanges
