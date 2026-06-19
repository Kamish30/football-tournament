"""Pydantic schemas for API validation."""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


# ── Auth ─────────────────────────────────────────────────────
class LoginRequest(BaseModel):
    username: str
    password: str

class LoginResponse(BaseModel):
    token: str
    username: str
    display_name: str
    role: str

class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=4)
    display_name: str = Field(min_length=1, max_length=100)
    role: str = "editor"


# ── Groups ───────────────────────────────────────────────────
class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    birth_year: int = Field(ge=2000, le=2025)

class GroupOut(BaseModel):
    id: int
    name: str
    birth_year: int
    team_count: int = 0
    match_count: int = 0
    played_count: int = 0
    class Config:
        from_attributes = True


# ── Teams ────────────────────────────────────────────────────
class TeamCreate(BaseModel):
    group_id: int
    name: str = Field(min_length=1, max_length=100)
    short_name: str = Field(min_length=1, max_length=10)

class TeamOut(BaseModel):
    id: int
    group_id: int
    name: str
    short_name: str
    class Config:
        from_attributes = True


# ── Players ──────────────────────────────────────────────────
class PlayerCreate(BaseModel):
    team_id: int
    full_name: str = Field(min_length=1, max_length=150)
    number: Optional[int] = None

class PlayerOut(BaseModel):
    id: int
    team_id: int
    full_name: str
    number: Optional[int]
    team_name: str = ""
    team_short: str = ""
    class Config:
        from_attributes = True


# ── Matches ──────────────────────────────────────────────────
class MatchEventIn(BaseModel):
    player_id: int
    type: str = Field(pattern="^(goal|assist)$")
    minute: Optional[int] = Field(default=None, ge=1, le=120)

class MatchCreate(BaseModel):
    group_id: int
    round: int = Field(ge=1, le=3)
    team_a_id: int
    team_b_id: int
    match_date: Optional[str] = None
    venue: str = ""

class MatchUpdate(BaseModel):
    score_a: int = Field(ge=0)
    score_b: int = Field(ge=0)
    own_goals_a: int = Field(ge=0, default=0)
    own_goals_b: int = Field(ge=0, default=0)
    gk_pts_a: int = Field(ge=0, le=2, default=0)
    gk_pts_b: int = Field(ge=0, le=2, default=0)
    status: str = "played"
    venue: str = ""
    match_date: Optional[str] = None
    version: int
    events: List[MatchEventIn] = []

class MatchOut(BaseModel):
    id: int
    group_id: int
    round: int
    team_a_id: int
    team_b_id: int
    team_a_name: str = ""
    team_b_name: str = ""
    team_a_short: str = ""
    team_b_short: str = ""
    match_date: Optional[str]
    venue: str
    status: str
    score_a: int
    score_b: int
    own_goals_a: int
    own_goals_b: int
    gk_pts_a: int
    gk_pts_b: int
    version: int
    events: list = []


# ── Standings ────────────────────────────────────────────────
class StandingRow(BaseModel):
    position: int
    team_id: int
    team_name: str
    short_name: str
    mp: int = 0
    w: int = 0
    d: int = 0
    l: int = 0
    gf: int = 0
    ga: int = 0
    gd: int = 0
    pts: int = 0

class GkStandingRow(BaseModel):
    position: int
    team_id: int
    team_name: str
    battles: int = 0
    wins: int = 0
    draws: int = 0
    losses: int = 0
    gk_pts: int = 0

class LeaderboardRow(BaseModel):
    position: int
    player_id: int
    player_name: str
    team_name: str
    number: Optional[int]
    count: int
