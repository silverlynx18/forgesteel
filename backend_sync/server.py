"""FastAPI application for Forge Steel central hero and retainer database.

Exposes RESTful endpoints for:
- Heroes management with Draw Steel characteristics and stamina tracking
- Shared Retainer roster with attack rolls, abilities, and independent stat blocks
- Party roster composition and multi-hero retainer associations
- Bidirectional offline synchronization with conflict resolution
"""

from __future__ import annotations
from contextlib import asynccontextmanager
from typing import List, Optional
from datetime import datetime

from fastapi import FastAPI, Depends, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from database import get_db, init_db
from models import (
    Party,
    Hero,
    Retainer,
    HeroRetainerAssignment,
    PartyCreate,
    PartyUpdate,
    PartyResponse,
    PartyRosterResponse,
    HeroCreate,
    HeroUpdate,
    HeroResponse,
    RetainerCreate,
    RetainerUpdate,
    RetainerResponse,
    HeroRetainerAssignmentCreate,
    HeroRetainerAssignmentResponse,
    SyncRequest,
    SyncResponse,
    utc_now,
)
from sync_service import SyncService


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    init_db()
    yield


app = FastAPI(
    title="Forge Steel Central Hero & Retainer Database",
    description="Central database extension for Forge Steel supporting shared party retainers, multi-hero association, and offline sync.",
    version="1.0.0",
    lifespan=lifespan,
)

# Enable CORS for browser local client integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health", tags=["Health"])
def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "forgesteel-central-db",
        "timestamp": utc_now().isoformat(),
    }


# ============================================================================
# Parties & Shared Rosters
# ============================================================================


@app.post("/api/parties", response_model=PartyResponse, status_code=status.HTTP_201_CREATED, tags=["Parties"])
def create_party(party_in: PartyCreate, db: Session = Depends(get_db)):
    """Create an adventuring party."""
    party = Party(
        name=party_in.name,
        description=party_in.description,
        user_id=party_in.user_id,
    )
    if party_in.id:
        party.id = party_in.id
    db.add(party)
    db.commit()
    db.refresh(party)
    return party


@app.get("/api/parties", response_model=List[PartyResponse], tags=["Parties"])
def list_parties(
    user_id: Optional[str] = None,
    include_deleted: bool = False,
    db: Session = Depends(get_db),
):
    """List parties."""
    query = db.query(Party)
    if not include_deleted:
        query = query.filter(Party.is_deleted == False)
    if user_id:
        query = query.filter(Party.user_id == user_id)
    return query.all()


@app.get("/api/parties/{party_id}", response_model=PartyResponse, tags=["Parties"])
def get_party(party_id: str, db: Session = Depends(get_db)):
    """Get party by ID."""
    party = db.query(Party).filter(Party.id == party_id).first()
    if not party or party.is_deleted:
        raise HTTPException(status_code=404, detail="Party not found")
    return party


@app.put("/api/parties/{party_id}", response_model=PartyResponse, tags=["Parties"])
def update_party(party_id: str, party_in: PartyUpdate, db: Session = Depends(get_db)):
    """Update party details."""
    party = db.query(Party).filter(Party.id == party_id).first()
    if not party:
        raise HTTPException(status_code=404, detail="Party not found")

    if party_in.name is not None:
        party.name = party_in.name
    if party_in.description is not None:
        party.description = party_in.description
    if party_in.user_id is not None:
        party.user_id = party_in.user_id
    if party_in.is_deleted is not None:
        party.is_deleted = party_in.is_deleted

    party.updated_at = utc_now()
    party.version += 1
    db.commit()
    db.refresh(party)
    return party


@app.delete("/api/parties/{party_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Parties"])
def delete_party(party_id: str, db: Session = Depends(get_db)):
    """Soft delete party."""
    party = db.query(Party).filter(Party.id == party_id).first()
    if not party:
        raise HTTPException(status_code=404, detail="Party not found")
    party.is_deleted = True
    party.updated_at = utc_now()
    party.version += 1
    db.commit()
    return None


@app.get("/api/parties/{party_id}/roster", response_model=PartyRosterResponse, tags=["Parties"])
def get_party_roster(party_id: str, db: Session = Depends(get_db)):
    """Retrieve full party roster: party info, heroes, shared retainers, and assignments."""
    party = db.query(Party).filter(Party.id == party_id, Party.is_deleted == False).first()
    if not party:
        raise HTTPException(status_code=404, detail="Party not found")

    heroes = db.query(Hero).filter(Hero.party_id == party_id, Hero.is_deleted == False).all()
    retainers = db.query(Retainer).filter(Retainer.party_id == party_id, Retainer.is_deleted == False).all()

    hero_ids = [h.id for h in heroes]
    assignments = (
        db.query(HeroRetainerAssignment)
        .filter(HeroRetainerAssignment.hero_id.in_(hero_ids), HeroRetainerAssignment.is_deleted == False)
        .all()
        if hero_ids
        else []
    )

    return PartyRosterResponse(
        party=PartyResponse.model_validate(party),
        heroes=[HeroResponse.model_validate(h) for h in heroes],
        shared_retainers=[RetainerResponse.model_validate(r) for r in retainers],
        assignments=[HeroRetainerAssignmentResponse.model_validate(a) for a in assignments],
    )


# ============================================================================
# Heroes
# ============================================================================


@app.post("/api/heroes", response_model=HeroResponse, status_code=status.HTTP_201_CREATED, tags=["Heroes"])
def create_hero(hero_in: HeroCreate, db: Session = Depends(get_db)):
    """Create a new hero."""
    hero = Hero(
        party_id=hero_in.party_id,
        name=hero_in.name,
        ancestry=hero_in.ancestry,
        hero_class=hero_in.hero_class,
        level=hero_in.level,
        stats=hero_in.stats.model_dump(),
        stamina_max=hero_in.stamina_max,
        stamina_current=hero_in.stamina_current,
        stamina_temp=hero_in.stamina_temp,
        recoveries_max=hero_in.recoveries_max,
        recoveries_current=hero_in.recoveries_current,
        speed=hero_in.speed,
        stability=hero_in.stability,
        victories=hero_in.victories,
        user_id=hero_in.user_id,
    )
    if hero_in.id:
        hero.id = hero_in.id
    db.add(hero)
    db.commit()
    db.refresh(hero)
    return hero


@app.get("/api/heroes", response_model=List[HeroResponse], tags=["Heroes"])
def list_heroes(
    party_id: Optional[str] = None,
    user_id: Optional[str] = None,
    include_deleted: bool = False,
    db: Session = Depends(get_db),
):
    """List heroes with optional filters."""
    query = db.query(Hero)
    if not include_deleted:
        query = query.filter(Hero.is_deleted == False)
    if party_id:
        query = query.filter(Hero.party_id == party_id)
    if user_id:
        query = query.filter(Hero.user_id == user_id)
    return query.all()


@app.get("/api/heroes/{hero_id}", response_model=HeroResponse, tags=["Heroes"])
def get_hero(hero_id: str, db: Session = Depends(get_db)):
    """Get hero details."""
    hero = db.query(Hero).filter(Hero.id == hero_id).first()
    if not hero or hero.is_deleted:
        raise HTTPException(status_code=404, detail="Hero not found")
    return hero


@app.put("/api/heroes/{hero_id}", response_model=HeroResponse, tags=["Heroes"])
def update_hero(hero_id: str, hero_in: HeroUpdate, db: Session = Depends(get_db)):
    """Update hero attributes."""
    hero = db.query(Hero).filter(Hero.id == hero_id).first()
    if not hero:
        raise HTTPException(status_code=404, detail="Hero not found")

    if hero_in.name is not None:
        hero.name = hero_in.name
    if hero_in.party_id is not None:
        hero.party_id = hero_in.party_id
    if hero_in.ancestry is not None:
        hero.ancestry = hero_in.ancestry
    if hero_in.hero_class is not None:
        hero.hero_class = hero_in.hero_class
    if hero_in.level is not None:
        hero.level = hero_in.level
    if hero_in.stats is not None:
        hero.stats = hero_in.stats.model_dump()
    if hero_in.stamina_max is not None:
        hero.stamina_max = hero_in.stamina_max
    if hero_in.stamina_current is not None:
        hero.stamina_current = hero_in.stamina_current
    if hero_in.stamina_temp is not None:
        hero.stamina_temp = hero_in.stamina_temp
    if hero_in.recoveries_max is not None:
        hero.recoveries_max = hero_in.recoveries_max
    if hero_in.recoveries_current is not None:
        hero.recoveries_current = hero_in.recoveries_current
    if hero_in.speed is not None:
        hero.speed = hero_in.speed
    if hero_in.stability is not None:
        hero.stability = hero_in.stability
    if hero_in.victories is not None:
        hero.victories = hero_in.victories
    if hero_in.user_id is not None:
        hero.user_id = hero_in.user_id
    if hero_in.is_deleted is not None:
        hero.is_deleted = hero_in.is_deleted

    hero.updated_at = utc_now()
    hero.version += 1
    db.commit()
    db.refresh(hero)
    return hero


@app.delete("/api/heroes/{hero_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Heroes"])
def delete_hero(hero_id: str, db: Session = Depends(get_db)):
    """Soft delete hero."""
    hero = db.query(Hero).filter(Hero.id == hero_id).first()
    if not hero:
        raise HTTPException(status_code=404, detail="Hero not found")
    hero.is_deleted = True
    hero.updated_at = utc_now()
    hero.version += 1
    db.commit()
    return None


@app.get("/api/heroes/{hero_id}/retainers", response_model=List[RetainerResponse], tags=["Heroes"])
def get_hero_retainers(hero_id: str, db: Session = Depends(get_db)):
    """List retainers assigned to accompany this hero."""
    hero = db.query(Hero).filter(Hero.id == hero_id, Hero.is_deleted == False).first()
    if not hero:
        raise HTTPException(status_code=404, detail="Hero not found")

    assignments = (
        db.query(HeroRetainerAssignment)
        .filter(
            HeroRetainerAssignment.hero_id == hero_id,
            HeroRetainerAssignment.active == True,
            HeroRetainerAssignment.is_deleted == False,
        )
        .all()
    )
    retainer_ids = [a.retainer_id for a in assignments]
    if not retainer_ids:
        return []

    retainers = db.query(Retainer).filter(Retainer.id.in_(retainer_ids), Retainer.is_deleted == False).all()
    return retainers


# ============================================================================
# Retainers (Shared Party Roster)
# ============================================================================


@app.post("/api/retainers", response_model=RetainerResponse, status_code=status.HTTP_201_CREATED, tags=["Retainers"])
def create_retainer(retainer_in: RetainerCreate, db: Session = Depends(get_db)):
    """Create a retainer in the shared party roster."""
    retainer = Retainer(
        party_id=retainer_in.party_id,
        name=retainer_in.name,
        retainer_type=retainer_in.retainer_type,
        level=retainer_in.level,
        stats=retainer_in.stats.model_dump(),
        stamina_max=retainer_in.stamina_max,
        stamina_current=retainer_in.stamina_current,
        stamina_temp=retainer_in.stamina_temp,
        recoveries_max=retainer_in.recoveries_max,
        recoveries_current=retainer_in.recoveries_current,
        abilities=[a.model_dump() for a in retainer_in.abilities],
        user_id=retainer_in.user_id,
    )
    if retainer_in.id:
        retainer.id = retainer_in.id
    db.add(retainer)
    db.commit()
    db.refresh(retainer)
    return retainer


@app.get("/api/retainers", response_model=List[RetainerResponse], tags=["Retainers"])
def list_retainers(
    party_id: Optional[str] = None,
    user_id: Optional[str] = None,
    include_deleted: bool = False,
    db: Session = Depends(get_db),
):
    """List retainers with optional filters."""
    query = db.query(Retainer)
    if not include_deleted:
        query = query.filter(Retainer.is_deleted == False)
    if party_id:
        query = query.filter(Retainer.party_id == party_id)
    if user_id:
        query = query.filter(Retainer.user_id == user_id)
    return query.all()


@app.get("/api/retainers/{retainer_id}", response_model=RetainerResponse, tags=["Retainers"])
def get_retainer(retainer_id: str, db: Session = Depends(get_db)):
    """Get retainer details including full stat block and abilities."""
    retainer = db.query(Retainer).filter(Retainer.id == retainer_id).first()
    if not retainer or retainer.is_deleted:
        raise HTTPException(status_code=404, detail="Retainer not found")
    return retainer


@app.put("/api/retainers/{retainer_id}", response_model=RetainerResponse, tags=["Retainers"])
def update_retainer(retainer_id: str, retainer_in: RetainerUpdate, db: Session = Depends(get_db)):
    """Update retainer stats, stamina, recoveries, or abilities."""
    retainer = db.query(Retainer).filter(Retainer.id == retainer_id).first()
    if not retainer:
        raise HTTPException(status_code=404, detail="Retainer not found")

    if retainer_in.name is not None:
        retainer.name = retainer_in.name
    if retainer_in.party_id is not None:
        retainer.party_id = retainer_in.party_id
    if retainer_in.retainer_type is not None:
        retainer.retainer_type = retainer_in.retainer_type
    if retainer_in.level is not None:
        retainer.level = retainer_in.level
    if retainer_in.stats is not None:
        retainer.stats = retainer_in.stats.model_dump()
    if retainer_in.stamina_max is not None:
        retainer.stamina_max = retainer_in.stamina_max
    if retainer_in.stamina_current is not None:
        retainer.stamina_current = retainer_in.stamina_current
    if retainer_in.stamina_temp is not None:
        retainer.stamina_temp = retainer_in.stamina_temp
    if retainer_in.recoveries_max is not None:
        retainer.recoveries_max = retainer_in.recoveries_max
    if retainer_in.recoveries_current is not None:
        retainer.recoveries_current = retainer_in.recoveries_current
    if retainer_in.abilities is not None:
        retainer.abilities = [a.model_dump() for a in retainer_in.abilities]
    if retainer_in.user_id is not None:
        retainer.user_id = retainer_in.user_id
    if retainer_in.is_deleted is not None:
        retainer.is_deleted = retainer_in.is_deleted

    retainer.updated_at = utc_now()
    retainer.version += 1
    db.commit()
    db.refresh(retainer)
    return retainer


@app.delete("/api/retainers/{retainer_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Retainers"])
def delete_retainer(retainer_id: str, db: Session = Depends(get_db)):
    """Soft delete retainer."""
    retainer = db.query(Retainer).filter(Retainer.id == retainer_id).first()
    if not retainer:
        raise HTTPException(status_code=404, detail="Retainer not found")
    retainer.is_deleted = True
    retainer.updated_at = utc_now()
    retainer.version += 1
    db.commit()
    return None


@app.get("/api/retainers/{retainer_id}/heroes", response_model=List[HeroResponse], tags=["Retainers"])
def get_retainer_heroes(retainer_id: str, db: Session = Depends(get_db)):
    """List all heroes accompanied by this shared retainer (multi-hero association)."""
    retainer = db.query(Retainer).filter(Retainer.id == retainer_id, Retainer.is_deleted == False).first()
    if not retainer:
        raise HTTPException(status_code=404, detail="Retainer not found")

    assignments = (
        db.query(HeroRetainerAssignment)
        .filter(
            HeroRetainerAssignment.retainer_id == retainer_id,
            HeroRetainerAssignment.active == True,
            HeroRetainerAssignment.is_deleted == False,
        )
        .all()
    )
    hero_ids = [a.hero_id for a in assignments]
    if not hero_ids:
        return []

    heroes = db.query(Hero).filter(Hero.id.in_(hero_ids), Hero.is_deleted == False).all()
    return heroes


# ============================================================================
# Assignments (Multi-Hero Retainer Linkage)
# ============================================================================


@app.post(
    "/api/assignments",
    response_model=HeroRetainerAssignmentResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Assignments"],
)
def assign_retainer_to_hero(assignment_in: HeroRetainerAssignmentCreate, db: Session = Depends(get_db)):
    """Assign a retainer to accompany a hero for a session or campaign."""
    hero = db.query(Hero).filter(Hero.id == assignment_in.hero_id, Hero.is_deleted == False).first()
    if not hero:
        raise HTTPException(status_code=404, detail="Hero not found")

    retainer = db.query(Retainer).filter(Retainer.id == assignment_in.retainer_id, Retainer.is_deleted == False).first()
    if not retainer:
        raise HTTPException(status_code=404, detail="Retainer not found")

    # Check for existing assignment
    assignment = (
        db.query(HeroRetainerAssignment)
        .filter(
            HeroRetainerAssignment.hero_id == assignment_in.hero_id,
            HeroRetainerAssignment.retainer_id == assignment_in.retainer_id,
            HeroRetainerAssignment.session_id == assignment_in.session_id,
            HeroRetainerAssignment.is_deleted == False,
        )
        .first()
    )

    if assignment:
        assignment.active = assignment_in.active
        assignment.role_description = assignment_in.role_description
        assignment.updated_at = utc_now()
        assignment.version += 1
    else:
        assignment = HeroRetainerAssignment(
            hero_id=assignment_in.hero_id,
            retainer_id=assignment_in.retainer_id,
            session_id=assignment_in.session_id,
            role_description=assignment_in.role_description,
            active=assignment_in.active,
        )
        if assignment_in.id:
            assignment.id = assignment_in.id
        db.add(assignment)

    db.commit()
    db.refresh(assignment)
    return assignment


@app.get("/api/assignments", response_model=List[HeroRetainerAssignmentResponse], tags=["Assignments"])
def list_assignments(
    hero_id: Optional[str] = None,
    retainer_id: Optional[str] = None,
    session_id: Optional[str] = None,
    active: Optional[bool] = None,
    db: Session = Depends(get_db),
):
    """List hero-retainer assignments."""
    query = db.query(HeroRetainerAssignment).filter(HeroRetainerAssignment.is_deleted == False)
    if hero_id:
        query = query.filter(HeroRetainerAssignment.hero_id == hero_id)
    if retainer_id:
        query = query.filter(HeroRetainerAssignment.retainer_id == retainer_id)
    if session_id:
        query = query.filter(HeroRetainerAssignment.session_id == session_id)
    if active is not None:
        query = query.filter(HeroRetainerAssignment.active == active)
    return query.all()


@app.delete("/api/assignments/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Assignments"])
def unassign_retainer(assignment_id: str, db: Session = Depends(get_db)):
    """Deactivate or remove a retainer assignment."""
    assignment = db.query(HeroRetainerAssignment).filter(HeroRetainerAssignment.id == assignment_id).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")
    assignment.active = False
    assignment.is_deleted = True
    assignment.updated_at = utc_now()
    assignment.version += 1
    db.commit()
    return None


# ============================================================================
# Bidirectional Sync
# ============================================================================


@app.post("/api/sync", response_model=SyncResponse, tags=["Synchronization"])
def sync_data(request: SyncRequest, db: Session = Depends(get_db)):
    """Bidirectional sync between client cache (IndexedDB / LocalStorage) and central database.
    
    Accepts client-side offline modifications, reconciles conflicts via Last-Write-Wins,
    and returns all central server updates since client's last_synced_at.
    """
    service = SyncService(db)
    return service.sync(request)
