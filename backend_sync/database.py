"""Database configuration and session management for Forge Steel."""

import os
from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session

# Central database URL, defaults to local SQLite file for Forge Steel
DATABASE_URL = os.getenv("FORGESTEEL_DATABASE_URL", "sqlite:///./forgesteel.db")

# Create engine with thread-safety for SQLite
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency for database session lifecycle."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db(target_engine=None):
    """Initialize database tables."""
    eng = target_engine or engine
    Base.metadata.create_all(bind=eng)
