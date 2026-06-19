"""Football Tournament Manager — FastAPI application."""

from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from collections import defaultdict
from datetime import datetime

from db import get_db, init_db, Group, Team, Player, Match, MatchEvent, User
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

app = FastAPI(title="Football Tournament Manager")
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

@app.get("/group/{group_id}", response_class=HTMLResponse)
def page_group(request: Request, group_id: int):
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
    return [{"id": u.id, "username": u.username, "display_name": u.display_name, "role": u.role} for u in users]

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
    return [TeamOut(id=t.id, group_id=t.group_id, name=t.name, short_name=t.short_name) for t in q.all()]

@app.post("/api/teams")
def create_team(data: TeamCreate, db: Session = Depends(get_db), me=Depends(get_current_user)):
    if not db.query(Group).get(data.group_id):
        raise HTTPException(404, "Группа не найдена")
    t = Team(group_id=data.group_id, name=data.name, short_name=data.short_name)
    db.add(t)
    db.commit()
    db.refresh(t)
    return TeamOut(id=t.id, group_id=t.group_id, name=t.name, short_name=t.short_name)

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

@app.post("/api/players")
def create_player(data: PlayerCreate, db: Session = Depends(get_db), me=Depends(get_current_user)):
    if not db.query(Team).get(data.team_id):
        raise HTTPException(404, "Команда не найдена")
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
    if db.query(MatchEvent).filter_by(player_id=player_id).count() > 0:
        raise HTTPException(400, "Нельзя удалить — у игрока есть события в матчах")
    db.delete(p)
    db.commit()
    return {"ok": True}


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
    for t in teams:
        stats[t.id] = {"team_id": t.id, "team_name": t.name, "short_name": t.short_name,
                        "mp": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0, "gd": 0, "pts": 0}

    for m in played:
        a, b = stats.get(m.team_a_id), stats.get(m.team_b_id)
        if not a or not b:
            continue
        a["mp"] += 1; b["mp"] += 1
        a["gf"] += m.score_a; a["ga"] += m.score_b
        b["gf"] += m.score_b; b["ga"] += m.score_a
        if m.score_a > m.score_b:
            a["w"] += 1; a["pts"] += 3; b["l"] += 1
        elif m.score_a < m.score_b:
            b["w"] += 1; b["pts"] += 3; a["l"] += 1
        else:
            a["d"] += 1; b["d"] += 1; a["pts"] += 1; b["pts"] += 1

    rows = sorted(stats.values(), key=lambda r: (-r["pts"], -(r["gf"] - r["ga"]), -r["gf"]))
    for i, r in enumerate(rows):
        r["gd"] = r["gf"] - r["ga"]
        r["position"] = i + 1
    return rows


@app.get("/api/gk-standings")
def get_gk_standings(group_id: int, db: Session = Depends(get_db)):
    teams = db.query(Team).filter_by(group_id=group_id).all()
    played = db.query(Match).filter_by(group_id=group_id, status="played").all()

    stats = {}
    for t in teams:
        stats[t.id] = {"team_id": t.id, "team_name": t.name, "battles": 0, "wins": 0, "draws": 0, "losses": 0, "gk_pts": 0}

    for m in played:
        a, b = stats.get(m.team_a_id), stats.get(m.team_b_id)
        if not a or not b:
            continue
        if m.gk_pts_a == 0 and m.gk_pts_b == 0:
            continue
        a["battles"] += 1; b["battles"] += 1
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
