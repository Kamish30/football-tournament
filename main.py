"""Football Tournament Manager — FastAPI application."""

from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy.orm import Session
from collections import defaultdict
from datetime import datetime

from db import get_db, init_db, Group, Team, Player, Match, MatchEvent, User, CoachTeam, SessionLocal
from schemas import (
    LoginRequest, LoginResponse, UserCreate,
    GroupCreate, GroupOut, TeamCreate, TeamOut,
    PlayerCreate, PlayerOut, MatchCreate, MatchUpdate, MatchOut,
    StandingRow, GkStandingRow, LeaderboardRow, MatchEventIn,
)
from auth import (
    hash_password, verify_password, create_token,
    get_current_user, get_optional_user,
)

app = FastAPI(title="Савося")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.on_event("startup")
def startup():
    init_db()


# ── Pages (HTML) ─────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def page_home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/login", response_class=HTMLResponse)
def page_login(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/group/{identifier}", response_class=HTMLResponse)
def page_group(request: Request, identifier: str):
    db = SessionLocal()
    try:
        # Try birth_year first, then ID
        group = db.query(Group).filter_by(birth_year=int(identifier)).first() if identifier.isdigit() else None
        if not group and identifier.isdigit():
            group = db.query(Group).get(int(identifier))
        group_id = group.id if group else 0
    finally:
        db.close()
    return templates.TemplateResponse("group.html", {"request": request, "group_id": group_id})


# ── Auth API ─────────────────────────────────────────────────

@app.post("/api/login", response_model=LoginResponse)
def login(data: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(username=data.username).first()
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(400, "Неверный логин или пароль")
    token = create_token(user.id, user.username, user.role)
    return LoginResponse(token=token, username=user.username, display_name=user.display_name, role=user.role)

@app.post("/api/users")
def create_user(data: UserCreate, db: Session = Depends(get_db), me=Depends(get_current_user)):
    if me["role"] != "admin":
        raise HTTPException(403, "Только администратор может создавать пользователей")
    if db.query(User).filter_by(username=data.username).first():
        raise HTTPException(400, "Пользователь уже существует")
    user = User(username=data.username, password_hash=hash_password(data.password),
                display_name=data.display_name, role=data.role)
    db.add(user)
    db.commit()
    return {"id": user.id, "username": user.username}

@app.get("/api/users")
def list_users(db: Session = Depends(get_db), me=Depends(get_current_user)):
    if me["role"] != "admin":
        raise HTTPException(403, "Нет доступа")
    users = db.query(User).all()
    result = []
    for u in users:
        coach_teams = []
        if u.role == "coach":
            ct = db.query(CoachTeam).filter_by(user_id=u.id).all()
            for c in ct:
                t = db.query(Team).get(c.team_id)
                if t:
                    g = db.query(Group).get(t.group_id)
                    coach_teams.append({"team_id": t.id, "team_name": t.name, "group_name": g.name if g else "?"})
        result.append({"id": u.id, "username": u.username, "display_name": u.display_name, "role": u.role, "coach_teams": coach_teams})
    return result

@app.put("/api/users/{user_id}/teams")
def set_coach_teams(user_id: int, data: dict, db: Session = Depends(get_db), me=Depends(get_current_user)):
    if me["role"] != "admin":
        raise HTTPException(403, "Нет доступа")
    user = db.query(User).get(user_id)
    if not user:
        raise HTTPException(404)
    team_ids = data.get("team_ids", [])
    # Remove old assignments
    db.query(CoachTeam).filter_by(user_id=user_id).delete()
    # Add new
    for tid in team_ids:
        if db.query(Team).get(tid):
            db.add(CoachTeam(user_id=user_id, team_id=tid))
    db.commit()
    return {"ok": True}

@app.get("/api/users/me/teams")
def get_my_teams(db: Session = Depends(get_db), me=Depends(get_current_user)):
    if me["role"] != "coach":
        return []
    ct = db.query(CoachTeam).filter_by(user_id=me["sub"]).all()
    return [c.team_id for c in ct]

@app.put("/api/users/password")
def change_password(data: dict, db: Session = Depends(get_db), me=Depends(get_current_user)):
    old_pw = data.get("old_password", "")
    new_pw = data.get("new_password", "")
    if len(new_pw) < 4:
        raise HTTPException(400, "Новый пароль должен быть минимум 4 символа")
    user = db.query(User).get(me["sub"])
    if not user or not verify_password(old_pw, user.password_hash):
        raise HTTPException(400, "Неверный текущий пароль")
    user.password_hash = hash_password(new_pw)
    db.commit()
    return {"ok": True}

@app.put("/api/users/{user_id}")
def update_user(user_id: int, data: dict, db: Session = Depends(get_db), me=Depends(get_current_user)):
    if me["role"] != "admin":
        raise HTTPException(403, "Нет доступа")
    user = db.query(User).get(user_id)
    if not user:
        raise HTTPException(404, "Пользователь не найден")
    new_username = data.get("username", "").strip()
    new_display = data.get("display_name", "").strip()
    new_password = data.get("password", "")
    if new_username and new_username != user.username:
        existing = db.query(User).filter_by(username=new_username).first()
        if existing:
            raise HTTPException(400, "Логин уже занят")
        user.username = new_username
    if new_display:
        user.display_name = new_display
    if new_password:
        if len(new_password) < 4:
            raise HTTPException(400, "Пароль минимум 4 символа")
        user.password_hash = hash_password(new_password)
    db.commit()
    return {"id": user.id, "username": user.username, "display_name": user.display_name, "role": user.role}

@app.delete("/api/users/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db), me=Depends(get_current_user)):
    if me["role"] != "admin":
        raise HTTPException(403, "Нет доступа")
    user = db.query(User).get(user_id)
    if not user:
        raise HTTPException(404)
    if user.username == "admin":
        raise HTTPException(400, "Нельзя удалить главного администратора")
    db.delete(user)
    db.commit()
    return {"ok": True}


# ── Groups API ───────────────────────────────────────────────

@app.get("/api/groups")
def list_groups(db: Session = Depends(get_db)):
    groups = db.query(Group).order_by(Group.birth_year).all()
    result = []
    for g in groups:
        tc = db.query(Team).filter_by(group_id=g.id).count()
        mc = db.query(Match).filter_by(group_id=g.id).count()
        pc = db.query(Match).filter_by(group_id=g.id, status="played").count()
        result.append(GroupOut(id=g.id, name=g.name, birth_year=g.birth_year,
                               team_count=tc, match_count=mc, played_count=pc))
    return result

@app.post("/api/groups")
def create_group(data: GroupCreate, db: Session = Depends(get_db), me=Depends(get_current_user)):
    if db.query(Group).filter_by(birth_year=data.birth_year).first():
        raise HTTPException(400, f"Группа с годом рождения {data.birth_year} уже существует")
    g = Group(name=data.name, birth_year=data.birth_year)
    db.add(g)
    db.commit()
    db.refresh(g)
    return {"id": g.id, "name": g.name, "birth_year": g.birth_year}

@app.delete("/api/groups/{group_id}")
def delete_group(group_id: int, db: Session = Depends(get_db), me=Depends(get_current_user)):
    g = db.query(Group).get(group_id)
    if not g:
        raise HTTPException(404)
    db.delete(g)
    db.commit()
    return {"ok": True}


# ── Teams API ────────────────────────────────────────────────

@app.get("/api/teams")
def list_teams(group_id: int = 0, db: Session = Depends(get_db)):
    q = db.query(Team)
    if group_id:
        q = q.filter_by(group_id=group_id)
    return [TeamOut(id=t.id, group_id=t.group_id, name=t.name, short_name=t.short_name, logo=t.logo) for t in q.all()]

@app.post("/api/teams")
def create_team(data: TeamCreate, db: Session = Depends(get_db), me=Depends(get_current_user)):
    if not db.query(Group).get(data.group_id):
        raise HTTPException(404, "Группа не найдена")
    t = Team(group_id=data.group_id, name=data.name, short_name=data.short_name)
    db.add(t)
    db.commit()
    db.refresh(t)
    return TeamOut(id=t.id, group_id=t.group_id, name=t.name, short_name=t.short_name, logo=t.logo)

@app.delete("/api/teams/{team_id}")
def delete_team(team_id: int, db: Session = Depends(get_db), me=Depends(get_current_user)):
    t = db.query(Team).get(team_id)
    if not t:
        raise HTTPException(404)
    if db.query(Match).filter((Match.team_a_id == team_id) | (Match.team_b_id == team_id)).count() > 0:
        raise HTTPException(400, "Нельзя удалить — у команды есть матчи")
    db.delete(t)
    db.commit()
    return {"ok": True}


# ── Players API ──────────────────────────────────────────────

@app.get("/api/players")
def list_players(group_id: int = 0, team_id: int = 0, db: Session = Depends(get_db)):
    q = db.query(Player).join(Team)
    if group_id:
        q = q.filter(Team.group_id == group_id)
    if team_id:
        q = q.filter(Player.team_id == team_id)
    q = q.order_by(Team.name, Player.number)
    return [PlayerOut(id=p.id, team_id=p.team_id, full_name=p.full_name, number=p.number,
                      team_name=p.team.name, team_short=p.team.short_name) for p in q.all()]

def can_manage_players(me: dict, team_id: int, db: Session) -> bool:
    """Check if user can manage players for a team."""
    if me["role"] in ("admin", "editor"):
        return True
    if me["role"] == "coach":
        return db.query(CoachTeam).filter_by(user_id=me["sub"], team_id=team_id).first() is not None
    return False

@app.post("/api/players")
def create_player(data: PlayerCreate, db: Session = Depends(get_db), me=Depends(get_current_user)):
    if not db.query(Team).get(data.team_id):
        raise HTTPException(404, "Команда не найдена")
    if not can_manage_players(me, data.team_id, db):
        raise HTTPException(403, "Нет доступа к этой команде")
    p = Player(team_id=data.team_id, full_name=data.full_name, number=data.number)
    db.add(p)
    db.commit()
    db.refresh(p)
    return {"id": p.id, "full_name": p.full_name}

@app.delete("/api/players/{player_id}")
def delete_player(player_id: int, db: Session = Depends(get_db), me=Depends(get_current_user)):
    p = db.query(Player).get(player_id)
    if not p:
        raise HTTPException(404)
    if not can_manage_players(me, p.team_id, db):
        raise HTTPException(403, "Нет доступа к этой команде")
    if db.query(MatchEvent).filter_by(player_id=player_id).count() > 0:
        raise HTTPException(400, "Нельзя удалить — у игрока есть события в матчах")
    db.delete(p)
    db.commit()
    return {"ok": True}


# ── Quick Stats Entry ────────────────────────────────────────

@app.post("/api/events/add")
def add_event(data: dict, db: Session = Depends(get_db), me=Depends(get_current_user)):
    if me["role"] not in ("admin", "editor"):
        raise HTTPException(403, "Нет доступа")
    match_id = data.get("match_id")
    player_id = data.get("player_id")
    event_type = data.get("type", "goal")
    minute = data.get("minute")
    if not match_id or not player_id:
        raise HTTPException(400, "Укажите match_id и player_id")
    if event_type not in ("goal", "assist"):
        raise HTTPException(400, "type должен быть goal или assist")
    m = db.query(Match).get(match_id)
    if not m:
        raise HTTPException(404, "Матч не найден")
    ev = MatchEvent(match_id=match_id, player_id=player_id, type=event_type, minute=minute)
    db.add(ev)
    m.version += 1
    db.commit()
    return {"ok": True, "event_id": ev.id}

@app.delete("/api/events/{event_id}")
def remove_event(event_id: int, db: Session = Depends(get_db), me=Depends(get_current_user)):
    if me["role"] not in ("admin", "editor"):
        raise HTTPException(403, "Нет доступа")
    ev = db.query(MatchEvent).get(event_id)
    if not ev:
        raise HTTPException(404)
    m = db.query(Match).get(ev.match_id)
    if m:
        m.version += 1
    db.delete(ev)
    db.commit()
    return {"ok": True}

@app.get("/api/players/stats-summary")
def get_players_stats_summary(group_id: int, db: Session = Depends(get_db)):
    """Get goals/assists count for all players in a group."""
    teams_q = db.query(Team).filter_by(group_id=group_id).all()
    team_ids = [t.id for t in teams_q]
    players_q = db.query(Player).filter(Player.team_id.in_(team_ids)).order_by(Player.team_id, Player.number).all()
    match_ids = [m.id for m in db.query(Match).filter_by(group_id=group_id, status="played").all()]
    events = db.query(MatchEvent).filter(MatchEvent.match_id.in_(match_ids)).all() if match_ids else []
    goal_map = defaultdict(int)
    assist_map = defaultdict(int)
    for e in events:
        if e.type == "goal":
            goal_map[e.player_id] += 1
        elif e.type == "assist":
            assist_map[e.player_id] += 1
    result = []
    for p in players_q:
        t = next((t for t in teams_q if t.id == p.team_id), None)
        result.append({
            "id": p.id, "full_name": p.full_name, "number": p.number,
            "team_id": p.team_id, "team_name": t.name if t else "?",
            "goals": goal_map.get(p.id, 0), "assists": assist_map.get(p.id, 0),
        })
    return result


# ── Matches API ──────────────────────────────────────────────

def match_to_out(m: Match, db: Session) -> dict:
    ta = db.query(Team).get(m.team_a_id)
    tb = db.query(Team).get(m.team_b_id)
    events = []
    for e in db.query(MatchEvent).filter_by(match_id=m.id).all():
        p = db.query(Player).get(e.player_id)
        events.append({
            "id": e.id, "player_id": e.player_id, "type": e.type, "minute": e.minute,
            "player_name": p.full_name if p else "?", "player_number": p.number if p else None,
            "team_id": p.team_id if p else None,
        })
    return {
        "id": m.id, "group_id": m.group_id, "round": m.round,
        "team_a_id": m.team_a_id, "team_b_id": m.team_b_id,
        "team_a_name": ta.name if ta else "?", "team_b_name": tb.name if tb else "?",
        "team_a_short": ta.short_name if ta else "?", "team_b_short": tb.short_name if tb else "?",
        "match_date": m.match_date.isoformat() if m.match_date else None,
        "venue": m.venue or "", "status": m.status,
        "score_a": m.score_a, "score_b": m.score_b,
        "own_goals_a": m.own_goals_a, "own_goals_b": m.own_goals_b,
        "gk_pts_a": m.gk_pts_a, "gk_pts_b": m.gk_pts_b,
        "version": m.version, "events": events,
    }


@app.get("/api/matches")
def list_matches(group_id: int = 0, status: str = "", db: Session = Depends(get_db)):
    q = db.query(Match)
    if group_id:
        q = q.filter_by(group_id=group_id)
    if status:
        q = q.filter_by(status=status)
    q = q.order_by(Match.match_date.asc().nullslast(), Match.id)
    return [match_to_out(m, db) for m in q.all()]


@app.get("/api/matches/{match_id}")
def get_match(match_id: int, db: Session = Depends(get_db)):
    m = db.query(Match).get(match_id)
    if not m:
        raise HTTPException(404)
    return match_to_out(m, db)


@app.post("/api/matches")
def create_match(data: MatchCreate, db: Session = Depends(get_db), me=Depends(get_current_user)):
    if data.team_a_id == data.team_b_id:
        raise HTTPException(400, "Команда не может играть сама с собой")
    if not db.query(Group).get(data.group_id):
        raise HTTPException(404, "Группа не найдена")
    md = None
    if data.match_date:
        try:
            md = datetime.fromisoformat(data.match_date)
        except ValueError:
            pass
    m = Match(group_id=data.group_id, round=data.round, team_a_id=data.team_a_id,
              team_b_id=data.team_b_id, match_date=md, venue=data.venue)
    db.add(m)
    db.commit()
    db.refresh(m)
    return match_to_out(m, db)


@app.put("/api/matches/{match_id}")
def update_match(match_id: int, data: MatchUpdate, db: Session = Depends(get_db), me=Depends(get_current_user)):
    m = db.query(Match).get(match_id)
    if not m:
        raise HTTPException(404)
    # Optimistic locking
    if m.version != data.version:
        raise HTTPException(409, "Матч был изменён другим пользователем. Обновите страницу.")

    m.score_a = data.score_a
    m.score_b = data.score_b
    m.own_goals_a = data.own_goals_a
    m.own_goals_b = data.own_goals_b
    m.gk_pts_a = data.gk_pts_a
    m.gk_pts_b = data.gk_pts_b
    m.status = data.status
    m.venue = data.venue
    if data.match_date:
        try:
            m.match_date = datetime.fromisoformat(data.match_date)
        except ValueError:
            pass
    m.version += 1
    m.updated_by = me.get("username", "")
    m.updated_at = datetime.utcnow()

    # Replace events atomically
    db.query(MatchEvent).filter_by(match_id=match_id).delete()
    for ev in data.events:
        db.add(MatchEvent(match_id=match_id, player_id=ev.player_id, type=ev.type, minute=ev.minute))

    db.commit()
    db.refresh(m)
    return match_to_out(m, db)


@app.delete("/api/matches/{match_id}")
def delete_match(match_id: int, db: Session = Depends(get_db), me=Depends(get_current_user)):
    m = db.query(Match).get(match_id)
    if not m:
        raise HTTPException(404)
    db.delete(m)
    db.commit()
    return {"ok": True}


# ── Standings API ────────────────────────────────────────────

@app.get("/api/standings")
def get_standings(group_id: int, db: Session = Depends(get_db)):
    teams = db.query(Team).filter_by(group_id=group_id).all()
    played = db.query(Match).filter_by(group_id=group_id, status="played").all()

    stats = {}
    form = {}  # track last results for form indicator
    for t in teams:
        stats[t.id] = {"team_id": t.id, "team_name": t.name, "short_name": t.short_name,
                        "mp": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0, "gd": 0, "pts": 0}
        form[t.id] = []

    # Sort by date for correct form order
    played_sorted = sorted(played, key=lambda m: (m.match_date or datetime.min))
    for m in played_sorted:
        a, b = stats.get(m.team_a_id), stats.get(m.team_b_id)
        if not a or not b:
            continue
        a["mp"] += 1; b["mp"] += 1
        a["gf"] += m.score_a; a["ga"] += m.score_b
        b["gf"] += m.score_b; b["ga"] += m.score_a
        if m.score_a > m.score_b:
            a["w"] += 1; a["pts"] += 3; b["l"] += 1
            form[m.team_a_id].append("W"); form[m.team_b_id].append("L")
        elif m.score_a < m.score_b:
            b["w"] += 1; b["pts"] += 3; a["l"] += 1
            form[m.team_a_id].append("L"); form[m.team_b_id].append("W")
        else:
            a["d"] += 1; b["d"] += 1; a["pts"] += 1; b["pts"] += 1
            form[m.team_a_id].append("D"); form[m.team_b_id].append("D")

    rows = sorted(stats.values(), key=lambda r: (-r["pts"], -(r["gf"] - r["ga"]), -r["gf"]))
    for i, r in enumerate(rows):
        r["gd"] = r["gf"] - r["ga"]
        r["position"] = i + 1
        r["form"] = form.get(r["team_id"], [])[-5:]  # last 5 results
    return rows


@app.get("/api/gk-standings")
def get_gk_standings(group_id: int, db: Session = Depends(get_db)):
    teams = db.query(Team).filter_by(group_id=group_id).all()
    played = db.query(Match).filter_by(group_id=group_id, status="played").all()

    stats = {}
    for t in teams:
        stats[t.id] = {"team_id": t.id, "team_name": t.name, "battles": 0, "wins": 0, "draws": 0, "losses": 0, "gk_pts": 0, "gk_gf": 0, "gk_ga": 0}

    for m in played:
        a, b = stats.get(m.team_a_id), stats.get(m.team_b_id)
        if not a or not b:
            continue
        if m.gk_pts_a == 0 and m.gk_pts_b == 0:
            continue
        a["battles"] += 1; b["battles"] += 1
        a["gk_gf"] += m.gk_pts_a; a["gk_ga"] += m.gk_pts_b
        b["gk_gf"] += m.gk_pts_b; b["gk_ga"] += m.gk_pts_a
        if m.gk_pts_a > m.gk_pts_b:
            a["wins"] += 1; a["gk_pts"] += 2; b["losses"] += 1
        elif m.gk_pts_a < m.gk_pts_b:
            b["wins"] += 1; b["gk_pts"] += 2; a["losses"] += 1
        else:
            a["draws"] += 1; b["draws"] += 1; a["gk_pts"] += 1; b["gk_pts"] += 1

    rows = [r for r in stats.values() if r["battles"] > 0]
    rows.sort(key=lambda r: (-r["gk_pts"], -r["wins"]))
    for i, r in enumerate(rows):
        r["position"] = i + 1
    return rows


@app.get("/api/leaderboard")
def get_leaderboard(group_id: int, type: str = "goal", db: Session = Depends(get_db)):
    if type not in ("goal", "assist"):
        raise HTTPException(400, "type must be goal or assist")
    match_ids = [m.id for m in db.query(Match).filter_by(group_id=group_id, status="played").all()]
    if not match_ids:
        return []
    events = db.query(MatchEvent).filter(MatchEvent.match_id.in_(match_ids), MatchEvent.type == type).all()
    counts = defaultdict(int)
    for e in events:
        counts[e.player_id] += 1
    rows = []
    for pid, cnt in counts.items():
        p = db.query(Player).get(pid)
        t = db.query(Team).get(p.team_id) if p else None
        rows.append({
            "player_id": pid, "player_name": p.full_name if p else "?",
            "team_name": t.short_name if t else "?", "number": p.number if p else None, "count": cnt,
        })
    rows.sort(key=lambda r: -r["count"])
    for i, r in enumerate(rows):
        r["position"] = i + 1
    return rows[:20]


@app.get("/api/crosstable")
def get_crosstable(group_id: int, db: Session = Depends(get_db)):
    teams = db.query(Team).filter_by(group_id=group_id).order_by(Team.name).all()
    played = db.query(Match).filter_by(group_id=group_id, status="played").all()
    team_list = [{"id": t.id, "name": t.name, "short_name": t.short_name} for t in teams]
    matrix = {}
    for t in teams:
        matrix[t.id] = {}
    for m in played:
        a_id, b_id = m.team_a_id, m.team_b_id
        if a_id not in matrix:
            matrix[a_id] = {}
        if b_id not in matrix:
            matrix[b_id] = {}
        matrix[a_id].setdefault(b_id, []).append(f"{m.score_a}:{m.score_b}")
        matrix[b_id].setdefault(a_id, []).append(f"{m.score_b}:{m.score_a}")
    # Convert to serializable format
    matrix_out = {}
    for row_id, cols in matrix.items():
        matrix_out[str(row_id)] = {str(col_id): scores for col_id, scores in cols.items()}
    return {"teams": team_list, "matrix": matrix_out}


# ── Export API (CSV for Excel) ───────────────────────────────

import csv
import io

def make_csv(rows: list[list], filename: str) -> StreamingResponse:
    buf = io.StringIO()
    # BOM for Excel to recognize UTF-8
    buf.write('\ufeff')
    writer = csv.writer(buf, delimiter=';')
    for row in rows:
        writer.writerow(row)
    buf.seek(0)
    from urllib.parse import quote
    safe_filename = quote(filename)
    return StreamingResponse(
        buf, media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{safe_filename}"},
    )


@app.get("/api/export/standings")
def export_standings(group_id: int, db: Session = Depends(get_db)):
    group = db.query(Group).get(group_id)
    gname = group.name if group else "group"
    standings = get_standings(group_id=group_id, db=db)
    rows = [["#", "Команда", "И", "В", "Н", "П", "ГЗ", "ГП", "РМ", "Очки"]]
    for r in standings:
        rows.append([r["position"], r["team_name"], r["mp"], r["w"], r["d"], r["l"], r["gf"], r["ga"], r["gd"], r["pts"]])
    return make_csv(rows, f"standings_{gname}.csv")


@app.get("/api/export/matches")
def export_matches(group_id: int, db: Session = Depends(get_db)):
    group = db.query(Group).get(group_id)
    gname = group.name if group else "group"
    matches = db.query(Match).filter_by(group_id=group_id).order_by(Match.match_date.asc().nullslast()).all()
    rows = [["Круг", "Команда A", "Команда B", "Счёт A", "Счёт B", "Автоголы A", "Автоголы B", "Вратари A", "Вратари B", "Статус", "Дата", "Площадка"]]
    for m in matches:
        ta = db.query(Team).get(m.team_a_id)
        tb = db.query(Team).get(m.team_b_id)
        rows.append([
            m.round, ta.name if ta else "?", tb.name if tb else "?",
            m.score_a, m.score_b, m.own_goals_a, m.own_goals_b,
            m.gk_pts_a, m.gk_pts_b, m.status,
            m.match_date.strftime("%Y-%m-%d %H:%M") if m.match_date else "",
            m.venue or "",
        ])
    return make_csv(rows, f"matches_{gname}.csv")


@app.get("/api/export/scorers")
def export_scorers(group_id: int, db: Session = Depends(get_db)):
    group = db.query(Group).get(group_id)
    gname = group.name if group else "group"
    leaders = get_leaderboard(group_id=group_id, type="goal", db=db)
    rows = [["#", "Игрок", "Команда", "Номер", "Голы"]]
    for r in leaders:
        rows.append([r["position"], r["player_name"], r["team_name"], r.get("number", ""), r["count"]])
    return make_csv(rows, f"scorers_{gname}.csv")


@app.get("/api/export/assists")
def export_assists(group_id: int, db: Session = Depends(get_db)):
    group = db.query(Group).get(group_id)
    gname = group.name if group else "group"
    leaders = get_leaderboard(group_id=group_id, type="assist", db=db)
    rows = [["#", "Игрок", "Команда", "Номер", "Ассисты"]]
    for r in leaders:
        rows.append([r["position"], r["player_name"], r["team_name"], r.get("number", ""), r["count"]])
    return make_csv(rows, f"assists_{gname}.csv")


@app.get("/api/export/players")
def export_players(group_id: int, db: Session = Depends(get_db)):
    group = db.query(Group).get(group_id)
    gname = group.name if group else "group"
    players = db.query(Player).join(Team).filter(Team.group_id == group_id).order_by(Team.name, Player.number).all()
    rows = [["Команда", "Номер", "ФИО"]]
    for p in players:
        rows.append([p.team.name, p.number or "", p.full_name])
    return make_csv(rows, f"players_{gname}.csv")


@app.get("/api/export/crosstable")
def export_crosstable(group_id: int, db: Session = Depends(get_db)):
    group = db.query(Group).get(group_id)
    gname = group.name if group else "group"
    data = get_crosstable(group_id=group_id, db=db)
    teams = data["teams"]
    matrix = data["matrix"]
    header = ["Команда"] + [t["short_name"] for t in teams]
    rows = [header]
    for row_t in teams:
        line = [row_t["name"]]
        for col_t in teams:
            if row_t["id"] == col_t["id"]:
                line.append("—")
            else:
                scores = matrix.get(str(row_t["id"]), {}).get(str(col_t["id"]), [])
                line.append(", ".join(s.replace(":", "-") for s in scores) if scores else "")
        rows.append(line)
    return make_csv(rows, f"crosstable_{gname}.csv")


@app.get("/api/export/team-stats/{team_id}")
def export_team_stats(team_id: int, type: str = "goal", db: Session = Depends(get_db)):
    t = db.query(Team).get(team_id)
    if not t:
        raise HTTPException(404)
    g = db.query(Group).get(t.group_id)
    played = db.query(Match).filter(
        ((Match.team_a_id == team_id) | (Match.team_b_id == team_id)),
        Match.status == "played"
    ).order_by(Match.match_date.asc().nullslast()).all()
    dates = sorted(set(m.match_date.strftime("%d.%m") for m in played if m.match_date))
    match_date_map = {m.id: (m.match_date.strftime("%d.%m") if m.match_date else "?") for m in played}
    match_ids = [m.id for m in played]
    team_players = db.query(Player).filter_by(team_id=team_id).order_by(Player.number).all()
    player_ids = [p.id for p in team_players]
    events = db.query(MatchEvent).filter(
        MatchEvent.match_id.in_(match_ids), MatchEvent.player_id.in_(player_ids), MatchEvent.type == type
    ).all() if match_ids and player_ids else []
    # Build matrix
    data_map = {}
    for e in events:
        d = match_date_map.get(e.match_id, "?")
        data_map.setdefault(e.player_id, {})
        data_map[e.player_id][d] = data_map[e.player_id].get(d, 0) + 1
    label = "Бомбардиры" if type == "goal" else "Ассистенты"
    header = ["Игрок", "Σ"] + dates
    rows = [header]
    for p in team_players:
        pd = data_map.get(p.id, {})
        total = sum(pd.values())
        if total == 0:
            continue
        row = [f"#{p.number} {p.full_name}" if p.number else p.full_name, total]
        for d in dates:
            row.append(pd.get(d, ""))
        rows.append(row)
    rows.sort(key=lambda r: -r[1] if isinstance(r[1], int) else 0)
    tname = t.name
    return make_csv(rows, f"{label}_{tname}.csv")


# ── Generate Round Schedule ──────────────────────────────────
from itertools import combinations

@app.post("/api/matches/generate")
def generate_round(data: dict, db: Session = Depends(get_db), me=Depends(get_current_user)):
    group_id = data.get("group_id")
    round_num = data.get("round", 1)
    if not group_id or round_num not in (1, 2, 3):
        raise HTTPException(400, "Укажите group_id и round (1-3)")
    teams = db.query(Team).filter_by(group_id=group_id).all()
    if len(teams) < 2:
        raise HTTPException(400, "Нужно минимум 2 команды")
    # Check which pairs already exist for this round
    existing = db.query(Match).filter_by(group_id=group_id, round=round_num).all()
    existing_pairs = set()
    for m in existing:
        pair = tuple(sorted([m.team_a_id, m.team_b_id]))
        existing_pairs.add(pair)
    # Generate missing pairs
    created = 0
    for t1, t2 in combinations(teams, 2):
        pair = tuple(sorted([t1.id, t2.id]))
        if pair not in existing_pairs:
            m = Match(group_id=group_id, round=round_num, team_a_id=t1.id, team_b_id=t2.id)
            db.add(m)
            created += 1
    db.commit()
    return {"created": created, "message": f"Создано {created} матчей для круга {round_num}"}


# ── Player Stats ─────────────────────────────────────────────

@app.get("/api/players/{player_id}/stats")
def get_player_stats(player_id: int, db: Session = Depends(get_db)):
    p = db.query(Player).get(player_id)
    if not p:
        raise HTTPException(404)
    t = db.query(Team).get(p.team_id)
    # Get all events for this player
    events = db.query(MatchEvent).filter_by(player_id=player_id).all()
    goals = [e for e in events if e.type == "goal"]
    assists = [e for e in events if e.type == "assist"]
    # Get match details for each event
    match_ids = set(e.match_id for e in events)
    # Also find all matches where the player's team played
    team_matches = db.query(Match).filter(
        ((Match.team_a_id == p.team_id) | (Match.team_b_id == p.team_id)),
        Match.status == "played"
    ).all()
    # Build match log
    match_log = []
    for m in team_matches:
        ta = db.query(Team).get(m.team_a_id)
        tb = db.query(Team).get(m.team_b_id)
        opponent = tb.name if m.team_a_id == p.team_id else ta.name
        m_goals = [e for e in goals if e.match_id == m.id]
        m_assists = [e for e in assists if e.match_id == m.id]
        if m.team_a_id == p.team_id:
            score_own, score_opp = m.score_a, m.score_b
        else:
            score_own, score_opp = m.score_b, m.score_a
        result = "В" if score_own > score_opp else "П" if score_own < score_opp else "Н"
        match_log.append({
            "match_id": m.id, "opponent": opponent,
            "score": f"{score_own}:{score_opp}", "result": result,
            "goals": len(m_goals), "assists": len(m_assists),
            "goal_minutes": [e.minute for e in m_goals if e.minute],
            "assist_minutes": [e.minute for e in m_assists if e.minute],
            "date": m.match_date.strftime("%d.%m.%Y") if m.match_date else None,
        })
    return {
        "id": p.id, "full_name": p.full_name, "number": p.number,
        "team_id": t.id if t else 0, "team_name": t.name if t else "?", "team_short": t.short_name if t else "?",
        "total_goals": len(goals), "total_assists": len(assists),
        "matches_played": len(team_matches),
        "match_log": match_log,
    }


# ── Team Stats ───────────────────────────────────────────────

@app.get("/api/teams/{team_id}/stats")
def get_team_stats(team_id: int, db: Session = Depends(get_db)):
    t = db.query(Team).get(team_id)
    if not t:
        raise HTTPException(404)
    g = db.query(Group).get(t.group_id)
    played = db.query(Match).filter(
        ((Match.team_a_id == team_id) | (Match.team_b_id == team_id)),
        Match.status == "played"
    ).order_by(Match.match_date.asc().nullslast()).all()

    wins = draws = losses = gf = ga = 0
    streak = []
    match_log = []
    for m in played:
        if m.team_a_id == team_id:
            sf, sa = m.score_a, m.score_b
        else:
            sf, sa = m.score_b, m.score_a
        gf += sf; ga += sa
        opp_id = m.team_b_id if m.team_a_id == team_id else m.team_a_id
        opp = db.query(Team).get(opp_id)
        if sf > sa:
            wins += 1; r = "В"
        elif sf < sa:
            losses += 1; r = "П"
        else:
            draws += 1; r = "Н"
        streak.append(r)
        match_log.append({
            "opponent": opp.name if opp else "?", "opponent_id": opp_id,
            "score": f"{sf}:{sa}", "result": r,
            "date": m.match_date.strftime("%d.%m.%Y") if m.match_date else None,
        })

    # Current streak
    current_streak = ""
    if streak:
        last = streak[-1]
        count = 0
        for s in reversed(streak):
            if s == last:
                count += 1
            else:
                break
        labels = {"В": "побед", "П": "поражений", "Н": "ничьих"}
        current_streak = f"{count} {labels.get(last, '')} подряд"

    # Top scorer of team
    team_players = db.query(Player).filter_by(team_id=team_id).all()
    player_ids = [p.id for p in team_players]
    match_ids = [m.id for m in played]
    top_scorer = None
    top_assist = None
    if player_ids and match_ids:
        events = db.query(MatchEvent).filter(
            MatchEvent.match_id.in_(match_ids), MatchEvent.player_id.in_(player_ids)
        ).all()
        goal_counts = defaultdict(int)
        assist_counts = defaultdict(int)
        for e in events:
            if e.type == "goal":
                goal_counts[e.player_id] += 1
            elif e.type == "assist":
                assist_counts[e.player_id] += 1
        if goal_counts:
            top_pid = max(goal_counts, key=goal_counts.get)
            top_p = db.query(Player).get(top_pid)
            top_scorer = {"name": top_p.full_name, "number": top_p.number, "goals": goal_counts[top_pid], "id": top_pid}
        if assist_counts:
            top_aid = max(assist_counts, key=assist_counts.get)
            top_a = db.query(Player).get(top_aid)
            top_assist = {"name": top_a.full_name, "number": top_a.number, "assists": assist_counts[top_aid], "id": top_aid}

    # Stats by date matrices
    dates = sorted(set(
        m.match_date.strftime("%d.%m") for m in played if m.match_date
    ))
    match_date_map = {}  # match_id -> date string
    for m in played:
        match_date_map[m.id] = m.match_date.strftime("%d.%m") if m.match_date else "?"

    goals_by_date = {}  # player_id -> {date -> count}
    assists_by_date = {}
    if player_ids and match_ids:
        all_events = db.query(MatchEvent).filter(
            MatchEvent.match_id.in_(match_ids), MatchEvent.player_id.in_(player_ids)
        ).all()
        for e in all_events:
            d = match_date_map.get(e.match_id, "?")
            if e.type == "goal":
                goals_by_date.setdefault(e.player_id, {})
                goals_by_date[e.player_id][d] = goals_by_date[e.player_id].get(d, 0) + 1
            elif e.type == "assist":
                assists_by_date.setdefault(e.player_id, {})
                assists_by_date[e.player_id][d] = assists_by_date[e.player_id].get(d, 0) + 1

    players_list = [{"id": p.id, "name": p.full_name, "number": p.number} for p in team_players]

    return {
        "id": t.id, "name": t.name, "short_name": t.short_name,
        "logo": t.logo, "group_name": g.name if g else "?",
        "matches_played": len(played), "wins": wins, "draws": draws, "losses": losses,
        "goals_for": gf, "goals_against": ga, "goal_diff": gf - ga,
        "avg_scored": round(gf / len(played), 1) if played else 0,
        "avg_conceded": round(ga / len(played), 1) if played else 0,
        "current_streak": current_streak,
        "top_scorer": top_scorer, "top_assist": top_assist,
        "match_log": match_log,
        "dates": dates,
        "players_list": players_list,
        "goals_by_date": {str(k): v for k, v in goals_by_date.items()},
        "assists_by_date": {str(k): v for k, v in assists_by_date.items()},
    }


# ── Team Logo Upload ─────────────────────────────────────────

@app.put("/api/teams/{team_id}/logo")
def upload_logo(team_id: int, data: dict, db: Session = Depends(get_db), me=Depends(get_current_user)):
    t = db.query(Team).get(team_id)
    if not t:
        raise HTTPException(404)
    logo_data = data.get("logo", "")
    # Validate: must be a data URL or empty
    if logo_data and not logo_data.startswith("data:image/"):
        raise HTTPException(400, "Неверный формат изображения")
    # Limit size ~100KB base64
    if len(logo_data) > 150000:
        raise HTTPException(400, "Логотип слишком большой (максимум ~100КБ)")
    t.logo = logo_data if logo_data else None
    db.commit()
    return {"ok": True}


# ── Player Search ────────────────────────────────────────────

@app.get("/api/dashboard")
def get_dashboard(db: Session = Depends(get_db)):
    # Recent results (last 6 played matches across all groups)
    recent = db.query(Match).filter_by(status="played").order_by(Match.updated_at.desc()).limit(10).all()
    recent_matches = []
    for m in recent:
        ta = db.query(Team).get(m.team_a_id)
        tb = db.query(Team).get(m.team_b_id)
        g = db.query(Group).get(m.group_id)
        recent_matches.append({
            "id": m.id, "group_id": m.group_id, "group_name": g.name if g else "?",
            "birth_year": g.birth_year if g else 0,
            "team_a": ta.name if ta else "?", "team_b": tb.name if tb else "?",
            "team_a_short": ta.short_name if ta else "?", "team_b_short": tb.short_name if tb else "?",
            "team_a_logo": ta.logo if ta else None, "team_b_logo": tb.logo if tb else None,
            "score_a": m.score_a, "score_b": m.score_b,
            "date": m.match_date.strftime("%d.%m") if m.match_date else None,
        })
    # Upcoming matches (next 6 scheduled)
    upcoming = db.query(Match).filter_by(status="scheduled").order_by(Match.match_date.asc().nullslast()).limit(10).all()
    upcoming_matches = []
    for m in upcoming:
        ta = db.query(Team).get(m.team_a_id)
        tb = db.query(Team).get(m.team_b_id)
        g = db.query(Group).get(m.group_id)
        upcoming_matches.append({
            "id": m.id, "group_id": m.group_id, "group_name": g.name if g else "?",
            "birth_year": g.birth_year if g else 0,
            "team_a": ta.name if ta else "?", "team_b": tb.name if tb else "?",
            "team_a_logo": ta.logo if ta else None, "team_b_logo": tb.logo if tb else None,
            "date": m.match_date.strftime("%d.%m %H:%M") if m.match_date else "Дата TBD",
            "venue": m.venue or "",
        })
    # Top scorer across all groups
    all_goals = db.query(MatchEvent).filter_by(type="goal").all()
    goal_counts = defaultdict(int)
    for e in all_goals:
        goal_counts[e.player_id] += 1
    top_scorer = None
    if goal_counts:
        top_pid = max(goal_counts, key=goal_counts.get)
        p = db.query(Player).get(top_pid)
        t = db.query(Team).get(p.team_id) if p else None
        top_scorer = {
            "id": top_pid, "name": p.full_name if p else "?",
            "team": t.short_name if t else "?", "goals": goal_counts[top_pid],
            "number": p.number if p else None,
        }
    return {"recent": recent_matches, "upcoming": upcoming_matches, "top_scorer": top_scorer}


@app.get("/api/players/search")
def search_players(q: str = "", db: Session = Depends(get_db)):
    if not q or len(q) < 2:
        return []
    results = db.query(Player).join(Team).join(Group).filter(
        Player.full_name.ilike(f"%{q}%")
    ).order_by(Player.full_name).limit(20).all()
    return [{
        "id": p.id, "full_name": p.full_name, "number": p.number,
        "team_name": p.team.name, "team_short": p.team.short_name,
        "group_name": p.team.group.name, "group_id": p.team.group.id,
    } for p in results]


# ── Database Backup ──────────────────────────────────────────

@app.get("/api/backup")
def download_backup(me=Depends(get_current_user)):
    if me["role"] != "admin":
        raise HTTPException(403, "Только администратор может скачать бэкап")
    from db import DB_PATH
    import shutil
    backup_path = DB_PATH + ".backup"
    shutil.copy2(DB_PATH, backup_path)
    def file_iter():
        with open(backup_path, "rb") as f:
            while chunk := f.read(8192):
                yield chunk
        import os
        os.remove(backup_path)
    return StreamingResponse(
        file_iter(), media_type="application/octet-stream",
        headers={"Content-Disposition": "attachment; filename=tournament_backup.db"},
    )
