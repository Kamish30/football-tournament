"""Database models and session management."""

import os
from datetime import datetime
from sqlalchemy import (
    create_engine, Column, Integer, String, DateTime, ForeignKey,
    CheckConstraint, Index, Text, event, text
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

# Use /data/ for Railway Volume, fallback to local file
DATA_DIR = os.getenv("DATA_DIR", ".")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "tournament.db")
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DB_PATH}")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

# Enable WAL mode for better concurrent reads
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()

SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Models ──────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(128), nullable=False)
    display_name = Column(String(100), nullable=False)
    role = Column(String(20), default="editor")  # editor | admin
    created_at = Column(DateTime, default=datetime.utcnow)


class Group(Base):
    __tablename__ = "groups"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    birth_year = Column(Integer, nullable=False)
    teams = relationship("Team", back_populates="group", cascade="all, delete-orphan")
    matches = relationship("Match", back_populates="group", cascade="all, delete-orphan")


class Team(Base):
    __tablename__ = "teams"
    id = Column(Integer, primary_key=True, autoincrement=True)
    group_id = Column(Integer, ForeignKey("groups.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(100), nullable=False)
    short_name = Column(String(10), nullable=False)
    logo = Column(Text, nullable=True)  # base64 data URL
    group = relationship("Group", back_populates="teams")
    players = relationship("Player", back_populates="team", cascade="all, delete-orphan")


class CoachTeam(Base):
    __tablename__ = "coach_teams"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="CASCADE"), nullable=False)


class Player(Base):
    __tablename__ = "players"
    id = Column(Integer, primary_key=True, autoincrement=True)
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="CASCADE"), nullable=False)
    full_name = Column(String(150), nullable=False)
    number = Column(Integer, nullable=True)
    team = relationship("Team", back_populates="players")
    events = relationship("MatchEvent", back_populates="player")


class Match(Base):
    __tablename__ = "matches"
    id = Column(Integer, primary_key=True, autoincrement=True)
    group_id = Column(Integer, ForeignKey("groups.id", ondelete="CASCADE"), nullable=False)
    round = Column(Integer, nullable=False)
    team_a_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    team_b_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    match_date = Column(DateTime, nullable=True)
    venue = Column(Text, default="")
    status = Column(String(20), default="scheduled")  # scheduled|played|postponed|cancelled
    score_a = Column(Integer, default=0)
    score_b = Column(Integer, default=0)
    own_goals_a = Column(Integer, default=0)
    own_goals_b = Column(Integer, default=0)
    gk_pts_a = Column(Integer, default=0)
    gk_pts_b = Column(Integer, default=0)
    version = Column(Integer, default=1)
    updated_by = Column(String(100), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    group = relationship("Group", back_populates="matches")
    team_a = relationship("Team", foreign_keys=[team_a_id])
    team_b = relationship("Team", foreign_keys=[team_b_id])
    events = relationship("MatchEvent", back_populates="match", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("round IN (1,2,3)", name="ck_round"),
        CheckConstraint("team_a_id != team_b_id", name="ck_different_teams"),
        CheckConstraint("score_a >= 0", name="ck_score_a"),
        CheckConstraint("score_b >= 0", name="ck_score_b"),
        CheckConstraint("gk_pts_a >= 0", name="ck_gk_a"),
        CheckConstraint("gk_pts_b >= 0", name="ck_gk_b"),
        Index("ix_match_group_status", "group_id", "status"),
    )


class MatchEvent(Base):
    __tablename__ = "match_events"
    id = Column(Integer, primary_key=True, autoincrement=True)
    match_id = Column(Integer, ForeignKey("matches.id", ondelete="CASCADE"), nullable=False)
    player_id = Column(Integer, ForeignKey("players.id"), nullable=False)
    type = Column(String(10), nullable=False)  # goal | assist
    minute = Column(Integer, nullable=True)

    match = relationship("Match", back_populates="events")
    player = relationship("Player", back_populates="events")

    __table_args__ = (
        CheckConstraint("type IN ('goal','assist')", name="ck_event_type"),
    )


def init_db():
    """Create all tables, run migrations, create default admin."""
    Base.metadata.create_all(bind=engine)

    # Migration: fix gk_pts constraints (allow any score, not just 0/1/2)
    with engine.connect() as conn:
        try:
            # Check if old constraint exists by trying to insert a test value
            result = conn.execute(text("SELECT sql FROM sqlite_master WHERE name='matches' AND type='table'"))
            row = result.fetchone()
            if row and "IN (0,1,2)" in (row[0] or ""):
                print("Migrating matches table: removing gk_pts IN (0,1,2) constraint...")
                conn.execute(text("""
                    CREATE TABLE matches_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        group_id INTEGER REFERENCES groups(id) ON DELETE CASCADE,
                        round INTEGER CHECK (round IN (1,2,3)),
                        team_a_id INTEGER REFERENCES teams(id),
                        team_b_id INTEGER REFERENCES teams(id),
                        match_date TIMESTAMP,
                        venue TEXT DEFAULT '',
                        status VARCHAR(20) DEFAULT 'scheduled',
                        score_a INTEGER DEFAULT 0 CHECK (score_a >= 0),
                        score_b INTEGER DEFAULT 0 CHECK (score_b >= 0),
                        own_goals_a INTEGER DEFAULT 0 CHECK (own_goals_a >= 0),
                        own_goals_b INTEGER DEFAULT 0 CHECK (own_goals_b >= 0),
                        gk_pts_a INTEGER DEFAULT 0 CHECK (gk_pts_a >= 0),
                        gk_pts_b INTEGER DEFAULT 0 CHECK (gk_pts_b >= 0),
                        version INTEGER DEFAULT 1,
                        updated_by VARCHAR(100),
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        CHECK (team_a_id != team_b_id)
                    )
                """))
                conn.execute(text("""
                    INSERT INTO matches_new SELECT * FROM matches
                """))
                conn.execute(text("DROP TABLE matches"))
                conn.execute(text("ALTER TABLE matches_new RENAME TO matches"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_match_group_status ON matches (group_id, status)"))
                conn.commit()
                print("Migration complete!")
        except Exception as e:
            print(f"Migration check: {e}")

    # Migration: add logo column to teams
    with engine.connect() as conn:
        try:
            result = conn.execute(text("SELECT sql FROM sqlite_master WHERE name='teams' AND type='table'"))
            row = result.fetchone()
            if row and "logo" not in (row[0] or ""):
                print("Adding logo column to teams...")
                conn.execute(text("ALTER TABLE teams ADD COLUMN logo TEXT"))
                conn.commit()
                print("Logo column added!")
        except Exception as e:
            print(f"Logo migration: {e}")

    # Migration: create coach_teams table if not exists
    with engine.connect() as conn:
        try:
            result = conn.execute(text("SELECT name FROM sqlite_master WHERE name='coach_teams' AND type='table'"))
            if not result.fetchone():
                print("Creating coach_teams table...")
                conn.execute(text("""
                    CREATE TABLE coach_teams (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                        team_id INTEGER REFERENCES teams(id) ON DELETE CASCADE
                    )
                """))
                conn.commit()
                print("coach_teams table created!")
        except Exception as e:
            print(f"Coach teams migration: {e}")

    db = SessionLocal()
    try:
        if not db.query(User).filter_by(username="admin").first():
            from auth import hash_password
            admin = User(
                username="admin",
                password_hash=hash_password("admin123"),
                display_name="Администратор",
                role="admin",
            )
            db.add(admin)
            db.commit()
            print("Created default admin user: admin / admin123")
    finally:
        db.close()
