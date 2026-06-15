"""Pytest configuration and shared fixtures."""
import sys
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest


@pytest.fixture(scope="session")
def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


@pytest.fixture
def temp_db_path(tmp_path) -> str:
    """Create a temporary SQLite database path for testing."""
    return str(tmp_path / "test.db")


@pytest.fixture
def temp_engine(temp_db_path):
    """Create a SQLAlchemy engine over a temporary database."""
    from sqlalchemy import create_engine, event
    from model.orm_models import Base
    from sqlalchemy.pool import StaticPool

    engine = create_engine(
        f"sqlite:///{temp_db_path}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _set_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.close()

    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def temp_session(temp_engine):
    """Create a SQLAlchemy session for testing."""
    from sqlalchemy.orm import sessionmaker
    Session = sessionmaker(bind=temp_engine)
    session = Session()
    yield session
    session.close()
