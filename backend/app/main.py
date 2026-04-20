from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Request, Response
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from typing import List, Optional
from app.database import engine, SessionLocal
from app.models import Base, School, Tank, SchoolTank, ManufacturerTank, Match, match_schools, match_tanks, MatchResult, TankUpgrade, User, UserRole, ImportEvent, ImportTank, ImportApplication, SchoolTransactionLog
from app.data.schools import schools as school_data
from app.data.tanks import tanks as tank_data
import requests
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger
from dotenv import load_dotenv
from app.data.upgrades import upgrade_tree
from app.auth import get_current_user, create_access_token, verify_password, get_password_hash, ACCESS_TOKEN_EXPIRE_MINUTES, decode_access_token
from random import sample
import shutil
from datetime import datetime
from pathlib import Path
import pytz
import os
import uuid
from app.schemas import (
    BuyItem, BuyRequest, TransferRequest, MatchTankUpdate,
    MatchUpdateRequest, MatchCreateRequest, MatchResponse,
    MatchResultRequest, SchoolOut, UserRegister, UserLogin, Token, UserOut
)
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from threading import Lock
from collections import defaultdict

MSK = pytz.timezone('Europe/Moscow')
load_dotenv()

DAYS_RU = {
    "Monday": "Понедельник",
    "Tuesday": "Вторник",
    "Wednesday": "Среда",
    "Thursday": "Четверг",
    "Friday": "Пятница",
    "Saturday": "Суббота",
    "Sunday": "Воскресенье"
}

# ------------------------
# Создание таблиц
# ------------------------
Base.metadata.create_all(bind=engine)

app = FastAPI(title="GuP Schools API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8000", "https://*.ngrok-free.app"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = Path("gup.db")
BACKUP_DIR = Path("backups")
BACKUP_DIR.mkdir(exist_ok=True)

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.join(BASE_DIR, "..", "frontend")

UPLOAD_BG_DIR = os.path.join(FRONTEND_DIR, "uploads", "backgrounds")
os.makedirs(UPLOAD_BG_DIR, exist_ok=True)

BACKGROUNDS_DIR = os.path.join(FRONTEND_DIR, "images", "backgrounds")
os.makedirs(BACKGROUNDS_DIR, exist_ok=True)

app.mount("/frontend", StaticFiles(directory=FRONTEND_DIR), name="frontend")

TAX = 0.2

def backup_database():
    """Создаёт копию БД с меткой времени."""
    if not DB_PATH.exists():
        print(f"[BACKUP] Файл БД не найден: {DB_PATH}")
        return
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = BACKUP_DIR / f"gup_backup_{timestamp}.db"
    try:
        shutil.copy2(DB_PATH, backup_file)
        print(f"[BACKUP] Создан бэкап: {backup_file}")
        # Очистка старых бэкапов (оставляем последние 7)
        cleanup_old_backups()
    except Exception as e:
        print(f"[BACKUP] Ошибка: {e}")

def cleanup_old_backups(keep=7):
    """Удаляет старые бэкапы, оставляя только последние `keep` штук."""
    backups = sorted(BACKUP_DIR.glob("gup_backup_*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in backups[keep:]:
        old.unlink()
        print(f"[BACKUP] Удалён старый бэкап: {old}")

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    # Для всех HTML-страниц (можно по расширению или по пути)
    if request.url.path.startswith("/frontend/") and request.url.path.endswith(".html"):
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline'; img-src 'self' data:; media-src 'self'; object-src 'none';"
        # Более строгий вариант: script-src 'none' — но тогда сломаются ваши скрипты и d3.
        # Оставьте 'self' и 'unsafe-inline' для ваших скриптов.
    return response

# ------------------------
# Логирование операций (вспомогательная функция)
# ------------------------
def create_transaction_log(
    db: Session,
    school_id: int,
    amount: int,
    operation_type: str,
    description: str,
    reference_id: int = None,
    reference_type: str = None,
    operator_user_id: int = None,
    extra_data: dict = None
):
    log = SchoolTransactionLog(
        school_id=school_id,
        amount=amount,
        operation_type=operation_type,
        description=description,
        reference_id=reference_id,
        reference_type=reference_type,
        operator_user_id=operator_user_id,
        extra_data=extra_data
    )
    db.add(log)

# ------------------------
# SEED (без изменений, оставлен как был)
# ------------------------
@app.on_event("startup")
def seed():
    db: Session = SessionLocal()
    try:
        # --- Школы ---
        if db.query(School).count() == 0:
            for s in school_data:
                db.add(School(
                    id=s["id"],
                    name=s["name"].strip(),
                    balance=s.get("balance", 0)
                ))
            db.commit()

        # --- Танки ---
        if db.query(Tank).count() == 0:
            for t in tank_data:
                db.add(Tank(
                    name=t["name"].strip(),
                    price=t["price"],
                    rank=t.get("rank", 1),
                    br=t.get("br", 0),
                    t_type=t.get("t_type", "-")
                ))
            db.commit()

        # --- Производители (ManufacturerTank) ---
        def sync_manufacturer_tanks(db: Session):
            school_map = {
                "Pravda": [
                    "Т-26-4", "Т-60", "БТ-5", "Т-26 (cn)", "Т-26", "БТ-7", "БТ-7М", "Т-70",
                    "Т-80", "Т-50", "Т-28 (1938)", "Т-28", "Т-28Э", "Т-34 (1940)", "Т-34 (1941)",
                    "Т-34 (1942)", "Т-34 СТЗ", "Т-34-57", "Т-34-85 (Д-5Т)", "Т-34-85", "Т-34-85 СТП",
                    "Т-44", "Т-35", "КВ-1 (Л-11)", "КВ-2 (1939)", "СМК", "КВ-1С", "КВ-1 (ЗиС-5)", "КВ-85",
                    "ИС-1", "ИС-2", "ИС-2 (1944)", "ИС-3", "ИС-6", "СУ-57Б", "СУ-122",
                    "СУ-152", "СУ-85", "ИСУ-152", "СУ-100У", "СУ-85М", "ИСУ-122", "ИСУ-122С", "СУ-100"
                ],
                "Ooarai": ["I-Go-Ko", "Pz.35 (t)", "Pz.38(t) A", "Pz.IV F1", "M3 Lee", "Pz.IV F2", "Chi-Nu", "Pz.IV H",
                           "Chi-Ri II", "StuG III F", "StuG III G", "Jagdpanzer 38(t)", "B1 bis", "VK 45.01 (P)"],
                "Jatkosota": [
                    "Ha-Go", "Т-26", "Vickers Mk.E", "БТ-5", "Т-26 (cn)", "БТ-7", "BT-42", "Т-50(FIN)",
                    "Т-28", "Т-28Э", "Т-34 (1941)", "Т-34 (1942)", "Pz.IV J", "Т-34-85", "KV-1B",
                    "StuG III F", "StuG III G"],
                "St.Gloriana": ["A13 Mk. I", "Tetrach I", "A13 Mk. II", "Harry Hopkins", "Mark IV", "Mark V",
                    "Valentine I", "Valentine XI", "Crusader Mk II", "Crusader Mk III", "Valentine IX", "Cromwell V",
                    "Cromwell I", "Avenger", "Challenger", "Comet", "Centurion Mk.1", "Centurion Mk.3", "Independent",
                    "Matilda III", "Churchill I", "Churchill III", "Churchill VII", "TOG II", "Archer", "Gun Carrier",
                    "Tortoise"],
                "Saunders": ["M2A4", "M3 Stuart", "M22", "M3A1 Stuart", "M3A3 Stuart", "M5A1 Stuart", "M24 Chaffee",
                    "M2 Medium", "M3 Lee", "M4A3 (105)", "M4A1", "M4", "M4A4", "M4A2", "Sherman VC Firefly",
                    "M4A1 (76) W", "M4A2 (76) W USSR", "M4A2 (76) W", "M4A3 (76) W", "M4/T26", "T25", "M26",
                    "T14", "M6A1", "T1E1", "T1E1 (90)", "M4A3E2", "T26E1-1", "T34", "T32", "M10 GMC", "M36 (cn)",
                    "M36", "M36B2", "T28", "T95"],
                "Anzio": ["M11/39", "M13/40 (I)", "M13/40 (III)", "M14/41", "Turan I", "M15/42", "Celere Sahariano",
                    "P40", "Turan III", "L3/33 CC", "75/18 M41", "75/32 M41", "75/34 M42", "Zrinyi II", "105/25 M43", "75/34 M43", "75/46 M43"],
                "Kuromorimine": ["Pz.35 (t)", "Pz.38(t) A", "Pz.II C", "Pz.II F", "Pz.38(t) F", "Pz.38(t) n.A.", "Pz.III B",
                    "Pz.III E", "Pz.IV C", "Neubaufahrzeug", "Pz.III F", "Pz.IV E", "Pz.IV F1", "Pz.III J", "Pz.III J1", "Pz.III L",
                    "Pz.III N", "Pz.III M", "Pz.IV F2", "Pz.IV G", "Pz.IV H", "Pz.IV J", "VK 3002 (M)", "Panther D", "Panther A",
                    "Panther G", "Panther F", "VK 45.01 (P)", "Tiger H1", "Tiger E", "Tiger II (P)", "Tiger II (H)", "Maus",
                    "StuG III A", "StuH 42 G", "StuG III F", "StuG III G", "Jagdpanzer IV", "Jagdpanzer 38(t)", "Panzer IV/70 (V)", "Jagdpanther G1",
                    "Ferdinand", "Jagdtiger"],
                "Chi-Ha-Tan": ["Ha-Go", "I-Go-Ko", "Ke-Ni", "Ka-Mi", "Chi-Ha", "Ho-I", "Chi-Ha Kai", "Chi-He", "Chi-Nu", "Chi-To", "Chi-To Late",
                    "Chi-Ri II", "Ro-Go", "Ho-Ni III", "Ho-Ri Prototype", "Ho-Ri Production"],
                "BC Freedom": ["AMC.34 YR", "H.35", "FCM.36", "AMC.35 (ACG.1)", "H.39", "R.35(SA38)", "M22", "M5A1 Stuart", "S.35", "D2",
                    "M4A1", "M4A4", "M4A2", "Panther G", "AMX M4", "2C bis", "2C", "B1 bis", "ARL-44 (ACL-1)", "ARL-44", "AMR.35 ZT3", "Sau 40", "M10 GMC"],
                "BellWall": ["Т-26", "Pz.II C", "Pz.II F", "Т-70", "Pz.III J", "Pz.III J1", "Pz.III L", "Pz.III M", "Т-34 (1941)", "Т-34-85", "Т-44",
                    "Tiger E", "StuG III G", "Jagdpanther G1", "Elefant", "Jagdtiger"],
                "Viggen": ["Strv m/31", "Strv m/38", "Pz.38(t) A", "Strv m/40L", "Pz.38(t) F", "Strv m/41 S-2", "Lago 1",
                    "Strv m/42 EH", "Strv m/42 DT", "Sav m/43 (1944)"],
                "Yogurt": ["H.35", "Pz.38(t) A", "Pz.III F", "Pz.IV E", "Turan I", "Pz.IV G", "Pz.IV H", "Panther D", "Panther G",
                    "L3/33 CC", "StuG III F", "StuG III G", "Jagdpanzer 38(t)", "Panzer IV/70 (V)"]
            }
            for school_name, tank_names in school_map.items():
                school = db.query(School).filter_by(name=school_name.strip()).first()
                if not school:
                    print(f"❌ Школа не найдена: '{school_name}'")
                    continue
                for tank_name in tank_names:
                    tank = db.query(Tank).filter(Tank.name == tank_name.strip()).first()
                    if not tank:
                        print(f"❌ Танк не найден: '{tank_name}'")
                        continue
                    exists = db.query(ManufacturerTank).filter_by(
                        school_id=school.id, tank_id=tank.id
                    ).first()
                    if not exists:
                        db.add(ManufacturerTank(school_id=school.id, tank_id=tank.id))
                        print(f"✅ Добавлено: {school_name} → {tank_name}")
            db.commit()

        sync_manufacturer_tanks(db)

        # --- Улучшения (TankUpgrade) из upgrade_tree ---
        if db.query(TankUpgrade).count() == 0:
            def flatten_tree(tree, parent=None):
                edges = []
                for child, subtree in tree.items():
                    if parent:
                        edges.append((parent, child))
                    if subtree:
                        edges.extend(flatten_tree(subtree, child))
                return edges

            name_to_id = {tank.name: tank.id for tank in db.query(Tank).all()}
            direct_pairs = flatten_tree(upgrade_tree)
            for from_name, to_name in direct_pairs:
                from_id = name_to_id.get(from_name)
                to_id = name_to_id.get(to_name)
                if from_id and to_id:
                    db.add(TankUpgrade(from_tank_id=from_id, to_tank_id=to_id, is_direct=True))
                    db.add(TankUpgrade(from_tank_id=to_id, to_tank_id=from_id, is_direct=False))
                else:
                    print(f"⚠️ Не найдены танки для улучшения: {from_name} -> {to_name}")
            db.commit()
    finally:
        db.close()

# ------------------------
# Dependency
# ------------------------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ------------------------
# API: Школы
# ------------------------
@app.get("/schools/")
def get_schools(db: Session = Depends(get_db)):
    schools = db.query(School).all()
    return [{
        "id": s.id,
        "name": s.name,
        "balance": s.balance,
        "rating": s.rating,
        "wins": s.wins,
        "losses": s.losses,
        "win_streak": s.current_streak,      # для фронтенда
        "current_streak": s.current_streak,  # для обратной совместимости
        "max_streak": s.max_streak
    } for s in schools]

@app.get("/schools/{school_id}")
def get_school(school_id: int, db: Session = Depends(get_db)):
    school = db.get(School, school_id)
    if not school:
        raise HTTPException(404, "School not found")
    tanks = [
        {
            "id": st.tank.id,
            "name": st.tank.name,
            "quantity": st.quantity,
            "price": st.tank.price,
            "rank": st.tank.rank,
            "type": st.tank.t_type,
            "br": st.tank.br
        } for st in school.tanks
    ]
    return {
        "id": school.id,
        "name": school.name,
        "balance": school.balance,
        "tanks": tanks,
        "background_path": school.background_path,
        "rating": school.rating,
        "wins": school.wins,
        "losses": school.losses
    }

# ------------------------
# API: Танки
# ------------------------
@app.get("/tanks/")
def get_tanks(db: Session = Depends(get_db)):
    tanks = db.query(Tank).all()
    return [{"id": t.id, "name": t.name, "price": t.price, "rank": t.rank, "type": t.t_type, "br": t.br, "nation": t.nation} for t in tanks]

@app.get("/tanks/manufacturer/{school_id}")
def get_manufacturer(school_id: int, db: Session = Depends(get_db)):
    school = db.get(School, school_id)
    if not school:
        raise HTTPException(404, "School not found")
    return [
        {
            "id": mt.tank.id,
            "name": mt.tank.name,
            "price": mt.tank.price,
            "rank": mt.tank.rank,
            "br": mt.tank.br,
            "type": mt.tank.t_type,
            "nation": mt.tank.nation   # добавлено
        } for mt in school.manufacturer_tanks
    ]


@app.post("/buy/")
def buy_tanks(
        request: BuyRequest,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    lock = get_school_lock(request.school_id)
    with lock:
        # --- ВСЯ СУЩЕСТВУЮЩАЯ ЛОГИКА ПОКУПКИ (без изменений) ---
        school = db.get(School, request.school_id)
        if not school:
            raise HTTPException(404, "School not found")

        # Проверка прав (как у вас)
        has_right = current_user.is_admin or any(
            r.school_id == request.school_id and r.role in ["commander", "deputy"]
            for r in current_user.roles
        )
        if not has_right:
            raise HTTPException(403, "Недостаточно прав")

        total_cost = 0
        items_to_buy = []
        for item in request.items:
            tank = db.get(Tank, item.tank_id)
            if not tank:
                raise HTTPException(404, f"Tank {item.tank_id} not found")
            total_cost += tank.price * item.quantity
            items_to_buy.append((tank, item.quantity))

        if school.balance < total_cost:
            raise HTTPException(400, "Not enough balance")

        school.balance -= total_cost
        for tank, qty in items_to_buy:
            existing = db.query(SchoolTank).filter_by(school_id=school.id, tank_id=tank.id).first()
            if existing:
                existing.quantity += qty
            else:
                db.add(SchoolTank(school_id=school.id, tank_id=tank.id, quantity=qty))

        create_transaction_log(
            db=db,
            school_id=school.id,
            amount=-total_cost,
            operation_type="tank_purchase",
            description=f"Покупка {sum(item.quantity for item in request.items)} танков",
            extra_data={"items": [{"tank_id": t.id, "quantity": qty} for t, qty in items_to_buy]},
            operator_user_id=current_user.id
        )
        db.commit()
        return {"message": "Purchase successful"}


@app.post("/transfer/")
def transfer_money(
        request: TransferRequest,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    # Проверка прав: пользователь должен иметь право на отправку из from_school
    if not current_user.is_admin:
        has_right_from = any(
            r.school_id == request.from_school_id and r.role in ["commander", "deputy"]
            for r in current_user.roles
        )
        if not has_right_from:
            raise HTTPException(403, "У вас нет прав на перевод денег из этой школы")

    # Блокируем обе школы (порядок по ID, чтобы избежать deadlock)
    lock_from = get_school_lock(request.from_school_id)
    lock_to = get_school_lock(request.to_school_id)

    first_lock = lock_from if request.from_school_id < request.to_school_id else lock_to
    second_lock = lock_to if request.from_school_id < request.to_school_id else lock_from

    with first_lock:
        with second_lock:
            from_school = db.get(School, request.from_school_id)
            to_school = db.get(School, request.to_school_id)
            if not from_school or not to_school:
                raise HTTPException(404, "School not found")
            if from_school.id == to_school.id:
                raise HTTPException(400, "Cannot transfer to the same school")
            if request.amount <= 0:
                raise HTTPException(400, "Amount must be positive")
            if request.amount > from_school.balance:
                raise HTTPException(400, "Insufficient funds")

            received_amount = int(request.amount * (1 - TAX))
            from_school.balance -= request.amount
            to_school.balance += received_amount

            create_transaction_log(
                db=db,
                school_id=from_school.id,
                amount=-request.amount,
                operation_type="transfer_sent",
                description=f"Перевод в школу {to_school.name}",
                reference_id=to_school.id,
                reference_type="school",
                extra_data={"to_school_id": to_school.id, "tax": TAX, "received": received_amount},
                operator_user_id=current_user.id
            )
            create_transaction_log(
                db=db,
                school_id=to_school.id,
                amount=received_amount,
                operation_type="transfer_received",
                description=f"Перевод от школы {from_school.name}",
                reference_id=from_school.id,
                reference_type="school",
                extra_data={"from_school_id": from_school.id, "tax": TAX, "sent": request.amount},
                operator_user_id=current_user.id
            )
            db.commit()
            return {
                "from_school": {"id": from_school.id, "balance": from_school.balance},
                "to_school": {"id": to_school.id, "balance": to_school.balance},
                "sent": request.amount,
                "received": received_amount
            }

# ------------------------
# API: Матчи (с мягким удалением)
# ------------------------
from datetime import datetime, timedelta

@app.post("/matches/create/", response_model=MatchResponse)
def create_match(req: MatchCreateRequest, db: Session = Depends(get_db)):
    now = datetime.now()
    if req.date_time < now:
        raise HTTPException(400, "Дата не может быть в прошлом")
    if req.date_time > now + timedelta(days=7):
        raise HTTPException(400, "Матч можно создать максимум на 7 дней вперёд")

    match = Match(
        date_time=req.date_time,
        mode=req.mode,
        format=str(req.format),
        special_rules=req.special_rules,
        map_selection=req.map_selection,
        status="active"
    )
    db.add(match)
    db.commit()
    db.refresh(match)

    for school_id in req.team1_school_ids:
        school = db.get(School, school_id)
        if school:
            db.execute(match_schools.insert().values(match_id=match.id, school_id=school.id, team=1))
    for school_id in req.team2_school_ids:
        school = db.get(School, school_id)
        if school:
            db.execute(match_schools.insert().values(match_id=match.id, school_id=school.id, team=2))

    db.execute(match_tanks.delete().where(match_tanks.c.match_id == match.id))
    for t in req.tanks:
        db.execute(match_tanks.insert().values(
            match_id=match.id,
            school_id=t.school_id,
            tank_id=t.tank_id,
            quantity=t.quantity
        ))
    db.commit()

    # Отправляем сообщение в Discord (канал матчей)
    webhook_matches = os.getenv("DISCORD_WEBHOOK_MATCHES")
    if webhook_matches:
        content = generate_match_message(match, db)
        msg_id = send_discord_message(webhook_matches, content)
        if msg_id:
            match.discord_match_message_id = msg_id
            db.commit()

    def build_team(team_number):
        team = []
        schools = db.execute(
            match_schools.select().where(
                (match_schools.c.match_id == match.id) &
                (match_schools.c.team == team_number)
            )
        ).mappings().all()
        for s in schools:
            school = db.get(School, s["school_id"])
            tanks = []
            tank_rows = db.execute(
                match_tanks.select().where(
                    (match_tanks.c.match_id == match.id) &
                    (match_tanks.c.school_id == school.id)
                )
            ).mappings().all()
            for t in tank_rows:
                tank_obj = db.get(Tank, t["tank_id"])
                if not tank_obj:
                    continue
                tanks.append({
                    "school_id": t["school_id"],
                    "tank_id": t["tank_id"],
                    "quantity": t["quantity"],
                    "name": tank_obj.name,
                    "br": tank_obj.br
                })
            team.append({
                "id": school.id,
                "name": school.name,
                "tanks": tanks
            })
        return team

    return {
        "id": match.id,
        "date_time": match.date_time,
        "team1": build_team(1),
        "team2": build_team(2),
        "mode": match.mode,
        "format": match.format,
        "special_rules": match.special_rules,
        "map_selection": match.map_selection,
    }

@app.get("/matches/", response_model=List[MatchResponse])
def get_matches(db: Session = Depends(get_db)):
    matches = db.query(Match).filter(Match.status != "deleted").all()
    result = []
    for m in matches:
        teams = {1: [], 2: []}
        schools_in_match = db.execute(
            match_schools.select().where(match_schools.c.match_id == m.id)
        ).mappings().all()
        for row in schools_in_match:
            school = db.get(School, row["school_id"])
            if not school:
                continue
            school_data = {"id": school.id, "name": school.name}
            teams[row["team"]].append(school_data)

        tanks = []
        for mt in db.execute(match_tanks.select().where(match_tanks.c.match_id == m.id)).mappings():
            tank_obj = db.get(Tank, mt["tank_id"])
            if not tank_obj:
                continue
            tanks.append({
                "school_id": mt["school_id"],
                "tank_id": mt["tank_id"],
                "quantity": mt["quantity"],
                "name": tank_obj.name,
                "br": tank_obj.br
            })

        calculated = db.query(MatchResult).filter(
            MatchResult.match_id == m.id,
            MatchResult.calculated == True
        ).first() is not None

        result.append({
            "id": m.id,
            "date_time": m.date_time,
            "team1": teams[1],
            "team2": teams[2],
            "mode": m.mode,
            "format": m.format,
            "special_rules": m.special_rules,
            "map_selection": m.map_selection,
            "tanks": tanks,
            "calculated": calculated
        })
    return result

@app.get("/matches/{match_id}", response_model=MatchResponse)
def get_match(match_id: int, db: Session = Depends(get_db)):
    match = db.get(Match, match_id)
    if not match or match.status == "deleted":
        raise HTTPException(404, "Match not found")
    teams = {1: [], 2: []}
    for s in db.execute(match_schools.select().where(match_schools.c.match_id == match.id)).mappings():
        school = db.get(School, s["school_id"])
        if not school:
            continue
        tanks = []
        for t in db.execute(match_tanks.select().where(
            (match_tanks.c.match_id == match.id) &
            (match_tanks.c.school_id == school.id)
        )).mappings():
            tank_obj = db.get(Tank, t["tank_id"])
            if not tank_obj:
                continue
            tanks.append({
                "school_id": school.id,
                "tank_id": t["tank_id"],
                "quantity": t["quantity"],
                "name": tank_obj.name,
                "br": tank_obj.br
            })
        teams[s["team"]].append({"id": school.id, "name": school.name, "tanks": tanks})
    return {
        "id": match.id,
        "date_time": match.date_time,
        "team1": teams[1],
        "team2": teams[2],
        "mode": match.mode,
        "format": match.format,
        "special_rules": match.special_rules,
        "map_selection": match.map_selection,
        "tanks": [t for team in teams.values() for s in team for t in s["tanks"]]
    }


@app.delete("/matches/{match_id}/delete")
def delete_match(match_id: int, db: Session = Depends(get_db)):
    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(404, "Match not found")
    match.status = "deleted"
    db.commit()

    # Удаляем сообщение в Discord
    delete_match_message(match)

    return {"ok": True}

@app.put("/matches/{match_id}")
def update_match(match_id: int, req: MatchUpdateRequest, db: Session = Depends(get_db)):
    try:
        match = db.get(Match, match_id)
        if not match or match.status == "deleted":
            raise HTTPException(404, "Match not found")
        if isinstance(req.date_time, str):
            date_time_obj = datetime.fromisoformat(req.date_time.replace('Z', '+00:00'))
        else:
            date_time_obj = req.date_time
        match.date_time = date_time_obj
        match.mode = req.mode
        match.format = str(req.format)
        match.special_rules = req.special_rules
        match.map_selection = req.map_selection

        db.execute(match_schools.delete().where(match_schools.c.match_id == match.id))
        for sid in req.team1_school_ids:
            db.execute(match_schools.insert().values(match_id=match.id, school_id=sid, team=1))
        for sid in req.team2_school_ids:
            db.execute(match_schools.insert().values(match_id=match.id, school_id=sid, team=2))

        db.execute(match_tanks.delete().where(match_tanks.c.match_id == match.id))
        db.commit()
        for t in req.tanks:
            db.execute(match_tanks.insert().values(
                match_id=match.id,
                school_id=t.school_id,
                tank_id=t.tank_id,
                quantity=t.quantity
            ))
        db.commit()

        # Редактируем сообщение в Discord, если есть
        webhook_matches = os.getenv("DISCORD_WEBHOOK_MATCHES")
        if webhook_matches and match.discord_match_message_id:
            content = generate_match_message(match, db)
            edit_discord_message(webhook_matches, match.discord_match_message_id, content)

        return {"ok": True, "message": "Match updated successfully"}
    except Exception as e:
        db.rollback()
        print(f"ERROR: {e}")
        raise HTTPException(500, detail=str(e))

# ------------------------
# API: Результаты матчей (с логами)
# ------------------------
def get_match_rank(match_id: int, db: Session) -> int:
    tank_ids = db.execute(
        match_tanks.select().where(match_tanks.c.match_id == match_id)
    ).mappings().all()
    max_rank = 1
    for row in tank_ids:
        tank = db.get(Tank, row["tank_id"])
        if tank and tank.rank > max_rank:
            max_rank = tank.rank
    return max_rank

def calculate_payments(match, result_data: dict, db: Session) -> dict:
    rank = get_match_rank(match.id, db)
    base_winner = {1:20000, 2:40000, 3:60000, 4:80000, 5:100000}[rank]
    base_loser  = {1:15000, 2:30000, 3:45000, 4:60000, 5:75000}[rank]
    winner_team = result_data["winner_team"]

    tank_prices = {t.id: t.price for t in db.query(Tank).all()}

    team_losses = {1: 0, 2: 0}
    schools_data = {}
    mercenaries_by_team = {1: [], 2: []}
    for merc in result_data.get("mercenaries", []):
        mercenaries_by_team[merc["team"]].append(merc)

    for team_key in ["team1_schools", "team2_schools"]:
        team = 1 if team_key == "team1_schools" else 2
        for school in result_data[team_key]:
            school_id = school["school_id"]
            bonuses = school["bonuses"]
            penalties = school["penalties"]
            losses_cost = 0
            for death in school["tank_deaths"]:
                tank_id = death["tank_id"]
                deaths = death["deaths"]
                price = tank_prices.get(tank_id, 0)
                losses_cost += price * deaths
            schools_data[school_id] = {
                "team": team,
                "bonuses": bonuses,
                "penalties": penalties,
                "losses_cost": losses_cost
            }
            team_losses[team] += losses_cost

    team_kills = {1: team_losses[2], 2: team_losses[1]}
    team_base_reward = {}
    for team in [1,2]:
        team_base_reward[team] = base_winner if team == winner_team else base_loser
        team_base_reward[team] += int(team_kills[team] * 0.03)
        team_base_reward[team] -= int(team_losses[team] * 0.02)

    payments = {}
    for team in [1, 2]:
        mercs = mercenaries_by_team[team]
        team_total = team_base_reward[team]
        if team_total <= 0:
            for merc in mercs:
                payments[merc["school_id"]] = payments.get(merc["school_id"], 0) + 5000
            school_ids = [sid for sid, data in schools_data.items() if data["team"] == team]
            if school_ids:
                share = team_total // len(school_ids)
                for sid in school_ids:
                    school_bonus = schools_data[sid]["bonuses"] * 10000 * rank
                    school_penalty = schools_data[sid]["penalties"] * 10000 * rank
                    payment = share + school_bonus - school_penalty
                    payments[sid] = payments.get(sid, 0) + payment
        else:
            merc_share_total = 0
            merc_percentages = []
            for merc in mercs:
                percent = {"low": 0.05, "medium": 0.10, "high": 0.15}.get(merc["activity"], 0.05)
                merc_share = int(team_total * percent)
                merc_share_total += merc_share
                merc_percentages.append((merc["school_id"], merc_share))
            remaining = team_total - merc_share_total
            school_ids = [sid for sid, data in schools_data.items() if data["team"] == team]
            if school_ids:
                share_per_school = remaining // len(school_ids)
                for sid in school_ids:
                    school_bonus = schools_data[sid]["bonuses"] * 10000 * rank
                    school_penalty = schools_data[sid]["penalties"] * 10000 * rank
                    payment = share_per_school + school_bonus - school_penalty
                    payments[sid] = payment
            for merc_id, merc_payment in merc_percentages:
                payments[merc_id] = payments.get(merc_id, 0) + merc_payment
    return payments

def generate_detailed_report(match, result, req_data, payments, db):
    lines = []
    eng_weekday = match.date_time.strftime("%A")
    ru_weekday = DAYS_RU.get(eng_weekday, eng_weekday)
    dt = match.date_time.strftime(f"{ru_weekday}, %d.%m.%Y - %H:%M МСК")
    lines.append(dt)
    lines.append(f"Формат: {match.mode}, bo{match.format} ")
    lines.append(f"Спец. правила: {match.special_rules or 'Нет'}")
    lines.append(f"Карты: {match.map_selection}")
    lines.append("")
    judge_name = db.get(School, result.referee_school_id).name if result.referee_school_id else "Нет"
    lines.append(f"Судья: {judge_name}")
    lines.append("")
    winner_team = result.winner_team
    winner_name = "Команда 1" if winner_team == 1 else "Команда 2"
    lines.append(f"{winner_name} выигрывает {result.score}")
    lines.append("")

    for team_key, team_label in [("team1_schools", "Команда 1"), ("team2_schools", "Команда 2")]:
        lines.append(f"--- {team_label} ---")
        for school in req_data[team_key]:
            school_obj = db.get(School, school["school_id"])
            school_name = school_obj.name if school_obj else f"ID {school['school_id']}"
            lines.append(f"{school_name}:")
            lines.append(f"Бонусы: {school['bonuses']}")
            lines.append(f"Штрафы: {school['penalties']}")
            mercs = [m for m in req_data.get("mercenaries", []) if m["team"] == (1 if team_key == "team1_schools" else 2)]
            if mercs:
                lines.append("Наёмники:")
                for m in mercs:
                    merc_school = db.get(School, m["school_id"])
                    merc_name = merc_school.name if merc_school else f"ID {m['school_id']}"
                    activity_ru = {"low": "Низкая", "medium": "Средняя", "high": "Высокая"}.get(m["activity"], "Низкая")
                    lines.append(f"{merc_name} ({activity_ru})")
            else:
                lines.append("Наёмники: Нет")
            lines.append("Потери танков:")
            tank_deaths = {}
            for death in school["tank_deaths"]:
                tank_id = death["tank_id"]
                deaths = death["deaths"]
                tank_deaths[tank_id] = tank_deaths.get(tank_id, 0) + deaths
            for tank_id, total_deaths in tank_deaths.items():
                tank = db.get(Tank, tank_id)
                tank_name = tank.name if tank else f"ID {tank_id}"
                lines.append(f"x{total_deaths} - {tank_name}")
            lines.append("")
        if team_key == "team1_schools":
            lines.append("--- vs. ---")
            lines.append("")
    return "\n".join(lines)

def generate_summary_report(match, result, payments, db):
    lines = []
    team1_schools = []
    team2_schools = []
    schools_in_match = db.execute(
        match_schools.select().where(match_schools.c.match_id == match.id)
    ).mappings().all()
    for row in schools_in_match:
        school = db.get(School, row["school_id"])
        if not school:
            continue
        if row["team"] == 1:
            team1_schools.append(school)
        else:
            team2_schools.append(school)

    team1_names = [s.name for s in team1_schools] if team1_schools else ["?"]
    team2_names = [s.name for s in team2_schools] if team2_schools else ["?"]
    eng_weekday = match.date_time.strftime("%A")
    ru_weekday = DAYS_RU.get(eng_weekday, eng_weekday)
    dt = match.date_time.strftime(f"{ru_weekday}, %d.%m.%Y - %H:%M МСК")
    lines.append(f"Подсчёт: {', '.join(team1_names)} vs {', '.join(team2_names)}")
    lines.append(dt)
    lines.append(f"Формат: {match.mode}, bo{match.format}")
    lines.append(f"Спец. правила: {match.special_rules or 'Нет'}")
    lines.append(f"Карты: {match.map_selection}")
    lines.append("")
    lines.append("Победившие команды:")
    winner_team = result.winner_team
    teams = team1_schools if winner_team == 1 else team2_schools
    for school in teams:
        payment = payments.get(school.id, 0)
        lines.append(f"{school.name}: {payment}")
    lines.append("")
    lines.append("Проигравшие команды:")
    loser_team = 2 if winner_team == 1 else 1
    teams = team1_schools if loser_team == 1 else team2_schools
    for school in teams:
        payment = payments.get(school.id, 0)
        lines.append(f"{school.name}: {payment}")
    mercenaries = result.result_data.get("mercenaries", [])
    if mercenaries:
        lines.append("")
        lines.append("Наёмники:")
        for merc in mercenaries:
            merc_school = db.get(School, merc["school_id"])
            merc_name = merc_school.name if merc_school else f"ID {merc['school_id']}"
            payment = payments.get(merc["school_id"], 0)
            lines.append(f"{merc_name}: {payment}")
    if result.referee_school_id:
        judge_school = db.get(School, result.referee_school_id)
        if judge_school:
            judge_payment = payments.get(judge_school.id, 0)
            lines.append("")
            lines.append(f"Судья: {judge_school.name} (5%): {judge_payment}")
    return "\n".join(lines)

def send_discord_message(webhook_url, content):
    # Добавляем параметр wait=true, чтобы Discord вернул ID сообщения
    if "?" in webhook_url:
        url = f"{webhook_url}&wait=true"
    else:
        url = f"{webhook_url}?wait=true"
    data = {"content": content}
    try:
        response = requests.post(url, json=data)
        response.raise_for_status()
        # Теперь ответ будет 200 OK с JSON
        return response.json().get('id')
    except Exception as e:
        print(f"Ошибка отправки в Discord: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"Тело ответа: {e.response.text[:200]}")
        return None

@app.post("/matches/{match_id}/result")
def submit_match_result(match_id: int, req: MatchResultRequest, db: Session = Depends(get_db)):
    match = db.get(Match, match_id)
    if not match or match.status == "deleted":
        raise HTTPException(404, "Матч не найден")
    existing = db.query(MatchResult).filter(MatchResult.match_id == match_id).first()
    if existing:
        raise HTTPException(400, "Результат уже подан")
    result = MatchResult(
        match_id=match_id,
        referee_school_id=req.referee_school_id,
        winner_team=req.winner_team,
        score=req.score,
        result_data=req.dict(),
        calculated=False
    )
    db.add(result)
    db.commit()
    # Отправку убрали – будет в calculate
    return {"ok": True, "message": "Результат подан"}


@app.post("/matches/{match_id}/calculate")
def calculate_match_result(match_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    result = db.query(MatchResult).filter(MatchResult.match_id == match_id).first()
    if not result:
        raise HTTPException(400, "Результат ещё не подан")
    match = db.get(Match, match_id)
    if not match or match.status == "deleted":
        raise HTTPException(404, "Матч не найден")

    req_data = result.result_data
    payments = calculate_payments(match, req_data, db)

    referee_id = result.referee_school_id
    if referee_id:
        total_payout = sum(payments.values())
        judge_fee = int(total_payout * 0.05) if total_payout > 0 else 5000
        payments[referee_id] = payments.get(referee_id, 0) + judge_fee

    MIN_BALANCE = -1_000_000
    for school_id, amount in payments.items():
        school = db.get(School, school_id)
        if not school:
            continue
        new_balance = school.balance + amount
        if new_balance < MIN_BALANCE:
            raise HTTPException(400, f"У школы {school.name} баланс станет {new_balance}, что ниже минимального {MIN_BALANCE}")
        school.balance = new_balance

        # Логирование (без изменений)
        if school_id == referee_id:
            op_type, desc = "referee_reward", "Оплата судейства"
        elif any(merc["school_id"] == school_id for merc in req_data.get("mercenaries", [])):
            op_type, desc = "mercenary_reward", "Награда наёмника"
        else:
            op_type, desc = "match_reward", "Награда за матч"

        team1_names = [s.name for s in db.query(School).filter(School.id.in_([s["school_id"] for s in req_data["team1_schools"]])).all()]
        team2_names = [s.name for s in db.query(School).filter(School.id.in_([s["school_id"] for s in req_data["team2_schools"]])).all()]

        create_transaction_log(
            db=db,
            school_id=school_id,
            amount=amount,
            operation_type=op_type,
            description=desc,
            reference_id=match.id,
            reference_type="match",
            operator_user_id=current_user.id,
            extra_data={
                "match_id": match.id,
                "winner_team": result.winner_team,
                "score": result.score,
                "teams": {"team1": team1_names, "team2": team2_names}
            }
        )

    result.payments_snapshot = payments
    result.calculated = True

    # --- Отправка/обновление Discord ---
    webhook_results = os.getenv("DISCORD_WEBHOOK_RESULTS")
    webhook_payments = os.getenv("DISCORD_WEBHOOK_PAYMENTS")

    detailed_report = generate_detailed_report(match, result, req_data, payments, db)
    summary_report = generate_summary_report(match, result, payments, db)

    if webhook_results:
        if result.discord_result_message_id:
            edit_discord_message(webhook_results, result.discord_result_message_id, detailed_report)
        else:
            msg_id = send_discord_message(webhook_results, detailed_report)
            if msg_id:
                result.discord_result_message_id = msg_id
    if webhook_payments:
        if result.discord_payment_message_id:
            edit_discord_message(webhook_payments, result.discord_payment_message_id, summary_report)
        else:
            msg_id = send_discord_message(webhook_payments, summary_report)
            if msg_id:
                result.discord_payment_message_id = msg_id
    update_ratings_for_match(match, result, db)

    db.commit()
    return {"ok": True, "message": "Матч подсчитан, отчёты отправлены/обновлены в Discord"}

def edit_discord_message(webhook_url, message_id, new_content):
    base = webhook_url.rstrip('/')
    url = f"{base}/messages/{message_id}"
    data = {"content": new_content}
    try:
        response = requests.patch(url, json=data)
        response.raise_for_status()
        return True
    except Exception as e:
        print(f"Ошибка редактирования сообщения в Discord: {e}")
        return False

# ------------------------
# API: Улучшения, продажи, покупки танков (остальные)
# ------------------------
@app.get("/tanks/{tank_id}/upgrades")
def get_tank_upgrades(tank_id: int, db: Session = Depends(get_db)):
    from_tank = db.get(Tank, tank_id)
    if not from_tank:
        return []
    all_upgrades = db.query(TankUpgrade).all()
    graph = {}
    tank_prices = {t.id: t.price for t in db.query(Tank).all()}
    for up in all_upgrades:
        from_id = up.from_tank_id
        to_id = up.to_tank_id
        price_from = tank_prices.get(from_id, 0)
        price_to = tank_prices.get(to_id, 0)
        diff = abs(price_to - price_from)
        weight = diff if up.is_direct else diff // 2
        graph.setdefault(from_id, {})[to_id] = weight
    import heapq
    distances = {node: float('inf') for node in graph}
    distances[tank_id] = 0
    pq = [(0, tank_id)]
    while pq:
        cur_dist, node = heapq.heappop(pq)
        if cur_dist > distances[node]:
            continue
        for neighbor, weight in graph.get(node, {}).items():
            new_dist = cur_dist + weight
            if new_dist < distances[neighbor]:
                distances[neighbor] = new_dist
                heapq.heappush(pq, (new_dist, neighbor))
    result = []
    for target_id, cost in distances.items():
        if target_id == tank_id or cost == float('inf'):
            continue
        target_tank = db.get(Tank, target_id)
        if target_tank:
            result.append({
                "to_tank_id": target_tank.id,
                "to_tank_name": target_tank.name,
                "cost": cost
            })
    return result


@app.post("/schools/{school_id}/sell_tank")
def sell_tank(
        school_id: int,
        req: dict,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    lock = get_school_lock(school_id)
    with lock:
        tank_id = req.get("tank_id")
        if not tank_id:
            raise HTTPException(400, "Не указан tank_id")

        school = db.get(School, school_id)
        if not school:
            raise HTTPException(404, "Школа не найдена")

        has_right = current_user.is_admin or any(
            r.school_id == school_id and r.role in ["commander", "deputy"]
            for r in current_user.roles
        )
        if not has_right:
            raise HTTPException(403, "Недостаточно прав")

        school_tank = db.query(SchoolTank).filter(
            SchoolTank.school_id == school_id,
            SchoolTank.tank_id == tank_id
        ).first()
        if not school_tank or school_tank.quantity < 1:
            raise HTTPException(400, "У школы нет такого танка")

        tank = db.get(Tank, tank_id)
        if not tank:
            raise HTTPException(404, "Танк не найден")

        sell_price = int(tank.price * 0.6)
        if school_tank.quantity > 1:
            school_tank.quantity -= 1
        else:
            db.delete(school_tank)

        school.balance += sell_price

        create_transaction_log(
            db=db,
            school_id=school.id,
            amount=sell_price,
            operation_type="tank_sale",
            description=f"Продажа {tank.name}",
            extra_data={"tank_id": tank.id, "tank_name": tank.name},
            operator_user_id=current_user.id
        )
        db.commit()
        return {"ok": True, "new_balance": school.balance, "sold_price": sell_price}

@app.post("/schools/{school_id}/upgrade_tank")
def upgrade_tank(
        school_id: int,
        req: dict,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    from_tank_id = req.get("from_tank_id")
    to_tank_id = req.get("to_tank_id")
    if not from_tank_id or not to_tank_id:
        raise HTTPException(400, "Не указаны tank_id")

    from_tank = db.get(Tank, from_tank_id)
    if not from_tank:
        raise HTTPException(404, "Исходный танк не найден")

    # Проверка прав: админ, командир или зам этой школы
    has_right = current_user.is_admin or any(
        r.school_id == school_id and r.role in ["commander", "deputy"]
        for r in current_user.roles
    )
    if not has_right:
        raise HTTPException(403, "Недостаточно прав для улучшения танка для этой школы")

    # Построение графа улучшений (как в вашем коде)
    all_upgrades = db.query(TankUpgrade).all()
    tank_prices = {t.id: t.price for t in db.query(Tank).all()}
    graph = {}
    for up in all_upgrades:
        f_id = up.from_tank_id
        t_id = up.to_tank_id
        diff = abs(tank_prices.get(f_id, 0) - tank_prices.get(t_id, 0))
        weight = diff if up.is_direct else diff // 2
        graph.setdefault(f_id, {})[t_id] = weight

    import heapq
    distances = {node: float('inf') for node in graph}
    distances[from_tank_id] = 0
    pq = [(0, from_tank_id)]
    while pq:
        cur_dist, node = heapq.heappop(pq)
        if cur_dist > distances[node]:
            continue
        for neighbor, weight in graph.get(node, {}).items():
            new_dist = cur_dist + weight
            if new_dist < distances[neighbor]:
                distances[neighbor] = new_dist
                heapq.heappush(pq, (new_dist, neighbor))

    cost = distances.get(to_tank_id)
    if cost is None or cost == float('inf'):
        raise HTTPException(400, "Невозможно улучшить танк (нет пути)")

    school = db.get(School, school_id)
    if not school:
        raise HTTPException(404, "Школа не найдена")

    school_tank = db.query(SchoolTank).filter(
        SchoolTank.school_id == school_id,
        SchoolTank.tank_id == from_tank_id
    ).first()
    if not school_tank or school_tank.quantity < 1:
        raise HTTPException(400, "У школы нет такого танка для улучшения")

    if school.balance < cost:
        raise HTTPException(400, f"Недостаточно средств. Нужно {cost}, доступно {school.balance}")

    school.balance -= cost
    if school_tank.quantity > 1:
        school_tank.quantity -= 1
    else:
        db.delete(school_tank)

    target_tank = db.query(SchoolTank).filter(
        SchoolTank.school_id == school_id,
        SchoolTank.tank_id == to_tank_id
    ).first()
    if target_tank:
        target_tank.quantity += 1
    else:
        db.add(SchoolTank(school_id=school_id, tank_id=to_tank_id, quantity=1))

    # Лог с указанием оператора
    create_transaction_log(
        db=db,
        school_id=school.id,
        amount=-cost,
        operation_type="tank_upgrade",
        description=f"Улучшение {from_tank.name} → {db.get(Tank, to_tank_id).name}",
        extra_data={"from_tank_id": from_tank_id, "to_tank_id": to_tank_id},
        operator_user_id=current_user.id
    )

    db.commit()
    return {"ok": True, "new_balance": school.balance, "cost": cost}

# ------------------------
# API: Пользователи (регистрация, логин, me)
# ------------------------
@limiter.limit("5/minute")
@app.post("/register")
async def register(request: Request, req: UserRegister, db: Session = Depends(get_db)):
    if req.password != req.confirm_password:
        raise HTTPException(400, "Пароли не совпадают")
    if len(req.password) > 72:
        raise HTTPException(400, "Пароль не может быть длиннее 72 символов")
    existing = db.query(User).filter(User.username == req.username).first()
    if existing:
        raise HTTPException(400, "Пользователь уже существует")
    hashed = get_password_hash(req.password)
    user = User(username=req.username, password_hash=hashed)
    db.add(user)
    db.commit()
    db.refresh(user)

    token_data = {"user_id": user.id, "username": user.username, "roles": []}
    access_token = create_access_token(token_data)

    response = JSONResponse({"access_token": access_token, "token_type": "bearer"})
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=False,  # True для HTTPS (в продакшене), False для локальной разработки
        samesite="lax",
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/"
    )
    return response

@limiter.limit("5/minute")
@app.post("/login")
async def login(request: Request, req: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == req.username).first()
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(401, "Неверный логин или пароль")

    roles = [{"school_id": r.school_id, "role": r.role} for r in user.roles]
    token_data = {"user_id": user.id, "username": user.username, "roles": roles}
    access_token = create_access_token(token_data)

    response = JSONResponse({"access_token": access_token, "token_type": "bearer"})
    # Определяем secure в зависимости от схемы запроса
    secure = request.url.scheme == "https"
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/"
    )
    print(f"[LOGIN] Установлена cookie для {request.url.scheme} (secure={secure})")
    return response

@app.post("/logout")
def logout(response: Response):
    response.delete_cookie("access_token", path="/")
    return {"ok": True}

@app.get("/me")
def get_me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # Подгружаем свежие данные (на случай, если роли изменились)
    user = db.query(User).filter(User.id == current_user.id).first()
    roles = [{"school_id": r.school_id, "role": r.role} for r in (user.roles or [])]
    return {
        "id": user.id,
        "username": user.username,
        "roles": roles,
        "is_admin": user.is_admin
    }

# ------------------------
# Админ-панель (управление ролями) – без изменений
# ------------------------
@app.get("/admin/users")
def get_users(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not current_user.is_admin:
        raise HTTPException(403, "Доступ запрещён")
    users = db.query(User).all()
    return [{"id": u.id, "username": u.username} for u in users]

@app.get("/admin/schools")
def get_schools_for_admin(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not current_user.is_admin:
        raise HTTPException(403, "Доступ запрещён")
    schools = db.query(School).all()
    return [{"id": s.id, "name": s.name} for s in schools]

@app.get("/admin/roles/{user_id}")
def get_user_roles(user_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not current_user.is_admin:
        raise HTTPException(403, "Доступ запрещён")
    roles = db.query(UserRole).filter(UserRole.user_id == user_id).all()
    return [{"school_id": r.school_id, "role": r.role} for r in roles]


@app.post("/admin/assign_role")
def assign_role(req: dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not current_user.is_admin:
        raise HTTPException(403, "Доступ запрещён")
    user_id = req.get("user_id")
    school_id = req.get("school_id")
    role = req.get("role")
    if not user_id or not school_id or not role:
        raise HTTPException(400, "Не все поля заполнены")
    if role not in ["commander", "deputy"]:
        raise HTTPException(400, "Недопустимая роль")

    # Проверка лимита: не более 2 командиров и 2 заместителей на школу
    current_count = db.query(UserRole).filter(
        UserRole.school_id == school_id,
        UserRole.role == role
    ).count()
    MAX_COUNT = 2
    if current_count >= MAX_COUNT:
        raise HTTPException(400, f"Невозможно назначить: в школе уже {current_count} {role}(ов). Максимум {MAX_COUNT}.")

    # Удаляем старую роль пользователя в этой школе (если была)
    existing = db.query(UserRole).filter_by(user_id=user_id, school_id=school_id).first()
    if existing:
        db.delete(existing)
    new_role = UserRole(user_id=user_id, school_id=school_id, role=role)
    db.add(new_role)
    db.commit()
    return {"ok": True}

@app.delete("/admin/remove_role")
def remove_role(req: dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not current_user.is_admin:
        raise HTTPException(403, "Доступ запрещён")
    user_id = req.get("user_id")
    school_id = req.get("school_id")
    role = req.get("role")
    db.query(UserRole).filter_by(user_id=user_id, school_id=school_id, role=role).delete()
    db.commit()
    return {"ok": True}

@app.get("/")
def root():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/frontend/index.html")

# ------------------------
# Импорт (админские эндпоинты) – с логами и правильным планированием
# ------------------------
def run_import_draw(event_id: int):
    """Функция розыгрыша импорта (вызывается по расписанию или вручную)."""
    db = SessionLocal()
    try:
        event = db.query(ImportEvent).filter(ImportEvent.id == event_id).first()
        if not event or event.is_drawn or not event.is_active:
            print(f"[IMPORT DRAW] Импорт {event_id} уже разыгран или неактивен")
            return
        print(f"[IMPORT DRAW] Начинаем розыгрыш импорта {event_id}")
        import_tanks = db.query(ImportTank).filter(ImportTank.event_id == event.id).all()
        for it in import_tanks:
            apps = db.query(ImportApplication).filter(
                ImportApplication.event_id == event.id,
                ImportApplication.tank_id == it.tank_id
            ).all()
            if not apps:
                continue
            winner = sample(apps, 1)[0]
            school = winner.school
            if school.balance >= it.price:
                school.balance -= it.price
                school_tank = db.query(SchoolTank).filter_by(school_id=school.id, tank_id=it.tank_id).first()
                if school_tank:
                    school_tank.quantity += 1
                else:
                    db.add(SchoolTank(school_id=school.id, tank_id=it.tank_id, quantity=1))
                it.winner_school_id = school.id
                create_transaction_log(
                    db=db,
                    school_id=school.id,
                    amount=-it.price,
                    operation_type="import_purchase",
                    description=f"Покупка танка {it.tank.name} через импорт (авто)",
                    reference_id=event.id,
                    reference_type="import",
                    operator_user_id=winner.user_id,  # <-- добавлено
                    extra_data={"tank_id": it.tank_id, "tank_name": it.tank.name}
                )
                print(f"[IMPORT DRAW] Школе {school.name} списано {it.price} за танк {it.tank.name}")
            else:
                print(f"[IMPORT DRAW] У школы {school.name} недостаточно средств: {school.balance} < {it.price}")
        event.is_drawn = True
        event.is_active = False
        db.commit()
        print(f"[IMPORT DRAW] Импорт {event.id} завершён")
    except Exception as e:
        print(f"[IMPORT DRAW] Ошибка: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
    finally:
        db.close()

def schedule_import_draw(event_id: int, end_date_utc: datetime):
    """Планирует однократный розыгрыш импорта на указанное время (UTC)."""
    job_id = f"draw_import_{event_id}"
    # Удаляем предыдущее задание, если есть
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    scheduler.add_job(
        func=run_import_draw,
        trigger=DateTrigger(run_date=end_date_utc),
        args=[event_id],
        id=job_id,
        replace_existing=True
    )
    print(f"[SCHEDULER] Запланирован розыгрыш импорта {event_id} на {end_date_utc} UTC")

@app.post("/admin/import/create")
def create_import(
    display_date: str,
    start_date: str,
    end_date: str,
    min_br: float = 0.3,
    max_br: float = 7.7,
    tanks_count: int = 8,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if not current_user.is_admin:
        raise HTTPException(403, "Access denied")
    try:
        display_naive = datetime.fromisoformat(display_date)
        start_naive = datetime.fromisoformat(start_date)
        end_naive = datetime.fromisoformat(end_date)
        display = MSK.localize(display_naive)
        start = MSK.localize(start_naive)
        end = MSK.localize(end_naive)
    except ValueError:
        raise HTTPException(400, "Неверный формат даты")
    if display >= start or start >= end:
        raise HTTPException(400, "Даты должны идти по порядку: отображение < начало заявок < окончание заявок")
    display_utc = display.astimezone(pytz.UTC)
    start_utc = start.astimezone(pytz.UTC)
    end_utc = end.astimezone(pytz.UTC)
    tanks = db.query(Tank).filter(Tank.br >= min_br, Tank.br <= max_br).all()
    if len(tanks) < tanks_count:
        raise HTTPException(400, f"Недостаточно танков в диапазоне BR [{min_br}, {max_br}]")
    selected = sample(tanks, tanks_count)
    event = ImportEvent(
        display_date=display_utc,
        start_date=start_utc,
        end_date=end_utc,
        min_br=min_br,
        max_br=max_br,
        tanks_count=tanks_count,
        is_active=True,
        is_drawn=False
    )
    db.add(event)
    db.flush()
    for tank in selected:
        db.add(ImportTank(event_id=event.id, tank_id=tank.id, price=int(tank.price * 1.3)))
    db.commit()
    # Планируем розыгрыш
    schedule_import_draw(event.id, end_utc)
    return {"ok": True, "event_id": event.id}

@app.get("/admin/imports")
def get_admin_imports(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not current_user.is_admin:
        raise HTTPException(403, "Access denied")
    events = db.query(ImportEvent).order_by(ImportEvent.created_at.desc()).all()
    result = []
    for e in events:
        display_utc = pytz.UTC.localize(e.display_date)
        start_utc = pytz.UTC.localize(e.start_date)
        end_utc = pytz.UTC.localize(e.end_date)
        created_utc = pytz.UTC.localize(e.created_at)
        result.append({
            "id": e.id,
            "display_date": display_utc.astimezone(MSK).isoformat(),
            "start_date": start_utc.astimezone(MSK).isoformat(),
            "end_date": end_utc.astimezone(MSK).isoformat(),
            "min_br": e.min_br,
            "max_br": e.max_br,
            "tanks_count": e.tanks_count,
            "is_active": e.is_active,
            "is_drawn": e.is_drawn,
            "created_at": created_utc.astimezone(MSK).isoformat()
        })
    return result

@app.delete("/admin/import/{event_id}")
def delete_import(event_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not current_user.is_admin:
        raise HTTPException(403, "Access denied")
    event = db.get(ImportEvent, event_id)
    if not event:
        raise HTTPException(404, "Импорт не найден")
    # Удаляем задание из планировщика
    job_id = f"draw_import_{event_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    db.query(ImportTank).filter(ImportTank.event_id == event_id).delete()
    db.query(ImportApplication).filter(ImportApplication.event_id == event_id).delete()
    db.delete(event)
    db.commit()
    return {"ok": True}

@app.patch("/admin/import/{event_id}/status")
def update_import_status(event_id: int, req: dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not current_user.is_admin:
        raise HTTPException(403, "Access denied")
    event = db.get(ImportEvent, event_id)
    if not event:
        raise HTTPException(404, "Импорт не найден")
    if "is_active" in req:
        event.is_active = req["is_active"]
        if not event.is_active:
            # Если импорт деактивирован, удаляем задание
            job_id = f"draw_import_{event_id}"
            if scheduler.get_job(job_id):
                scheduler.remove_job(job_id)
        elif event.is_active and not event.is_drawn and event.end_date > datetime.utcnow():
            # Если активирован снова и ещё не разыгран – планируем
            schedule_import_draw(event.id, event.end_date)
    db.commit()
    return {"ok": True}

@app.put("/admin/import/{event_id}")
def update_import(
    event_id: int,
    req: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if not current_user.is_admin:
        raise HTTPException(403, "Access denied")
    event = db.get(ImportEvent, event_id)
    if not event:
        raise HTTPException(404, "Импорт не найден")
    if event.is_drawn:
        raise HTTPException(400, "Нельзя редактировать уже разыгранный импорт")

    # Запрещаем редактирование, если приём заявок уже начался
    now_utc = datetime.utcnow()
    if event.start_date <= now_utc:
        raise HTTPException(400, "Редактирование невозможно: приём заявок уже начался")

    try:
        display_naive = datetime.fromisoformat(req["display_date"])
        start_naive = datetime.fromisoformat(req["start_date"])
        end_naive = datetime.fromisoformat(req["end_date"])
        display = MSK.localize(display_naive)
        start = MSK.localize(start_naive)
        end = MSK.localize(end_naive)
    except (KeyError, ValueError):
        raise HTTPException(400, "Неверный формат даты")
    if display >= start or start >= end:
        raise HTTPException(400, "Даты должны идти по порядку: отображение < начало заявок < окончание заявок")

    event.display_date = display.astimezone(pytz.UTC)
    event.start_date = start.astimezone(pytz.UTC)
    event.end_date = end.astimezone(pytz.UTC)
    event.min_br = req.get("min_br", event.min_br)
    event.max_br = req.get("max_br", event.max_br)
    new_tanks_count = req.get("tanks_count", event.tanks_count)

    # Если количество танков изменилось, перегенерируем список
    if new_tanks_count != event.tanks_count:
        # Удаляем старые танки импорта (и связанные заявки)
        db.query(ImportApplication).filter(ImportApplication.event_id == event.id).delete()
        db.query(ImportTank).filter(ImportTank.event_id == event.id).delete()
        # Выбираем новые танки
        tanks = db.query(Tank).filter(Tank.br >= event.min_br, Tank.br <= event.max_br).all()
        if len(tanks) < new_tanks_count:
            raise HTTPException(400, f"Недостаточно танков в диапазоне BR [{event.min_br}, {event.max_br}]")
        selected = sample(tanks, new_tanks_count)
        for tank in selected:
            db.add(ImportTank(event_id=event.id, tank_id=tank.id, price=int(tank.price * 1.3)))
        event.tanks_count = new_tanks_count

    db.commit()
    # Перепланируем розыгрыш
    if event.is_active and not event.is_drawn:
        schedule_import_draw(event.id, event.end_date)
    return {"ok": True}

@app.post("/admin/import/draw/{event_id}")
def draw_import(event_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not current_user.is_admin:
        raise HTTPException(403, "Access denied")
    event = db.get(ImportEvent, event_id)
    if not event:
        raise HTTPException(404, "Импорт не найден")
    if not event.is_active:
        raise HTTPException(400, "Импорт неактивен")
    if event.is_drawn:
        raise HTTPException(400, "Розыгрыш уже проведён")
    if datetime.now() < event.end_date:
        raise HTTPException(400, "Розыгрыш можно проводить только после окончания приёма заявок")
    # Удаляем задание, если оно было
    job_id = f"draw_import_{event_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    # Выполняем розыгрыш
    run_import_draw(event_id)
    return {"ok": True}

# ---------- ПУБЛИЧНЫЙ: СПИСОК ВСЕХ ИМПОРТОВ ----------
@app.get("/import/list")
def get_imports_list(request: Request, db: Session = Depends(get_db)):
    # Определяем school_id текущего пользователя (если авторизован)
    my_school_id = None
    token = request.cookies.get("access_token")
    if token:
        payload = decode_access_token(token)
        if payload:
            user_id = payload.get("user_id")
            if user_id:
                user = db.query(User).filter(User.id == user_id).first()
                if user and user.roles:
                    # Берём первую школу (аналогично /import/apply)
                    my_school_id = user.roles[0].school_id

    events = db.query(ImportEvent).order_by(ImportEvent.start_date.desc()).all()
    result = []
    for e in events:
        # Преобразование дат (как было)
        display_utc = pytz.UTC.localize(e.display_date)
        start_utc = pytz.UTC.localize(e.start_date)
        end_utc = pytz.UTC.localize(e.end_date)

        tanks = db.query(ImportTank).filter(ImportTank.event_id == e.id).all()
        tank_list = []
        for t in tanks:
            winner = db.get(School, t.winner_school_id) if t.winner_school_id else None

            # Проверка, подавала ли моя школа заявку на этот танк
            applied = False
            if my_school_id:
                app_exists = db.query(ImportApplication).filter(
                    ImportApplication.event_id == e.id,
                    ImportApplication.school_id == my_school_id,
                    ImportApplication.tank_id == t.tank_id
                ).first() is not None
                applied = app_exists

            tank_list.append({
                "id": t.id,
                "tank_id": t.tank_id,
                "tank_name": t.tank.name,
                "price": t.price,
                "winner_school": winner.name if winner else None,
                "applied_by_my_school": applied   # <-- добавляем поле
            })
        result.append({
            "id": e.id,
            "display_date": display_utc.astimezone(MSK).isoformat(),
            "start_date": start_utc.astimezone(MSK).isoformat(),
            "end_date": end_utc.astimezone(MSK).isoformat(),
            "is_active": e.is_active,
            "is_drawn": e.is_drawn,
            "tanks": tank_list
        })
    return result

@app.post("/import/apply")
def apply_for_import_tank(req: dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tank_import_id = req.get("tank_import_id")
    if not tank_import_id:
        raise HTTPException(400, "Не указан ID танка в импорте")
    if not current_user.roles:
        raise HTTPException(403, "У вас нет прав на подачу заявок (нет роли командира/зама)")
    school_id = current_user.roles[0].school_id
    import_tank = db.query(ImportTank).join(ImportEvent).filter(
        ImportTank.id == tank_import_id,
        ImportEvent.is_active == True,
        ImportEvent.is_drawn == False
    ).first()
    if not import_tank:
        raise HTTPException(400, "Танк не найден или импорт уже завершён")
    event = import_tank.event
    start_utc = pytz.UTC.localize(event.start_date)
    end_utc = pytz.UTC.localize(event.end_date)
    now_utc = datetime.now(pytz.UTC)
    if now_utc < start_utc or now_utc > end_utc:
        raise HTTPException(400, "Заявки принимаются только в указанный период")
    apps_count = db.query(ImportApplication).filter(
        ImportApplication.event_id == event.id,
        ImportApplication.school_id == school_id
    ).count()
    if apps_count >= 2:
        raise HTTPException(400, "Ваша школа уже подала максимальное количество заявок (2) на этот импорт")
    school = db.get(School, school_id)
    if not school or school.balance < import_tank.price:
        raise HTTPException(400, f"Недостаточно средств. Нужно {import_tank.price}, доступно {school.balance if school else 0}")
    application = ImportApplication(event_id=event.id, school_id=school_id, tank_id=import_tank.tank_id, user_id=current_user.id)
    db.add(application)
    db.commit()
    return {"ok": True, "message": "Заявка подана"}

# ------------------------
# Планировщик и восстановление заданий при старте
# ------------------------
scheduler = BackgroundScheduler()

def restore_import_jobs():
    """Восстанавливает задания для всех активных неразыгранных импортов при старте сервера."""
    db = SessionLocal()
    try:
        now_utc = datetime.utcnow()
        events = db.query(ImportEvent).filter(
            ImportEvent.is_active == True,
            ImportEvent.is_drawn == False
        ).all()
        for event in events:
            if event.end_date <= now_utc:
                # Время уже прошло – запускаем розыгрыш немедленно
                print(f"[STARTUP] Импорт {event.id} просрочен, запускаем розыгрыш сейчас")
                run_import_draw(event.id)
            else:
                # Планируем на будущее
                schedule_import_draw(event.id, event.end_date)
    except Exception as e:
        print(f"[STARTUP] Ошибка восстановления заданий: {e}")
    finally:
        db.close()

# Запускаем планировщик и восстанавливаем задания
scheduler.start()
scheduler.add_job(
    func=backup_database,
    trigger="cron",
    hour=6,
    minute=0,
    id="daily_backup",
    replace_existing=True
)
print("[SCHEDULER] Запланировано ежедневное резервное копирование в 6:00")
restore_import_jobs()

@app.on_event("shutdown")
def shutdown_scheduler():
    scheduler.shutdown()

# ------------------------
# Эндпоинты для фонов (картинки, видео, загрузка)
# ------------------------
@app.get("/schools/backgrounds/list")
def list_backgrounds():
    if not os.path.exists(BACKGROUNDS_DIR):
        return []
    files = []
    for f in os.listdir(BACKGROUNDS_DIR):
        if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.mp4')):
            files.append(f"/frontend/images/backgrounds/{f}")
    return files

@app.post("/schools/{school_id}/set_background")
def set_school_background(
        school_id: int,
        req: dict,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    school = db.get(School, school_id)
    if not school:
        raise HTTPException(404, "Школа не найдена")
    has_right = current_user.is_admin or any(
        r.school_id == school_id and r.role in ["commander", "deputy"]
        for r in current_user.roles
    )
    if not has_right:
        raise HTTPException(403, "Недостаточно прав")
    bg_path = req.get("background_path")
    if bg_path:
        full_path = os.path.join(FRONTEND_DIR, bg_path.lstrip("/frontend/"))
        if not os.path.exists(full_path):
            raise HTTPException(400, "Фоновое изображение не найдено")
    school.background_path = bg_path
    db.commit()
    return {"ok": True, "background_path": bg_path}


@app.post("/schools/{school_id}/upload_background")
async def upload_school_background(
        school_id: int,
        file: UploadFile = File(...),
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    school = db.get(School, school_id)
    if not school:
        raise HTTPException(404, "Школа не найдена")

    has_right = current_user.is_admin or any(
        r.school_id == school_id and r.role in ["commander", "deputy"]
        for r in current_user.roles
    )
    if not has_right:
        raise HTTPException(403, "Недостаточно прав")

    # 1. Запрещаем SVG по MIME-типу и расширению
    if file.content_type == "image/svg+xml" or file.filename.lower().endswith('.svg'):
        raise HTTPException(400, "SVG файлы запрещены из соображений безопасности")

    # 2. Разрешаем только изображения и видео (кроме SVG)
    if not file.content_type.startswith(('image/', 'video/')):
        raise HTTPException(400, "Файл должен быть изображением или видео")

    # 3. Дополнительная проверка расширений (белый список)
    allowed_extensions = ('.png', '.jpg', '.jpeg', '.webp', '.mp4', '.webm', '.mov')
    if not any(file.filename.lower().endswith(ext) for ext in allowed_extensions):
        raise HTTPException(400, "Недопустимый формат файла. Разрешены: png, jpg, jpeg, webp, mp4, webm, mov")

    # 4. Генерируем безопасное имя (расширение берём из оригинального файла, но без SVG)
    ext = file.filename.split(".")[-1].lower()
    if ext not in ['png', 'jpg', 'jpeg', 'webp', 'mp4', 'webm', 'mov']:
        raise HTTPException(400, "Недопустимое расширение файла")

    filename = f"bg_{school_id}_{uuid.uuid4().hex}.{ext}"
    file_path = os.path.join(UPLOAD_BG_DIR, filename)
    contents = await file.read()

    # 5. Простейшая проверка магических байтов (для изображений)
    # PNG: первые 8 байт: 89 50 4E 47 0D 0A 1A 0A
    # JPEG: начало: FF D8 FF
    # WEBP: начало: 52 49 46 46 ... 57 45 42 50
    # MP4: начало: ... можно не проверять, полагаемся на расширение и content-type
    # Если нужно, можно добавить проверку через PIL, но для простоты пропустим.

    with open(file_path, "wb") as f:
        f.write(contents)

    # Удаляем старый фон, если есть
    # Удаляем старый фон, если есть
    if school.background_path:
        old_path = os.path.join(FRONTEND_DIR, school.background_path.lstrip("/frontend/"))
        if os.path.exists(old_path):
            try:
                os.remove(old_path)
            except PermissionError:
                # Файл занят, просто пропускаем удаление
                print(f"Не удалось удалить старый файл фона: {old_path} (файл занят)")

    relative_path = f"/frontend/uploads/backgrounds/{filename}"
    school.background_path = relative_path
    db.commit()
    return {"ok": True, "path": relative_path}

# ------------------------
# Эндпоинт для получения логов школы
# ------------------------
@app.get("/logs/school/{school_id}")
def get_school_logs(
    school_id: int,
    limit: int = 50,
    offset: int = 0,
    operation_type: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    school = db.get(School, school_id)
    if not school:
        raise HTTPException(404, "Школа не найдена")
    has_right = current_user.is_admin or any(
        r.school_id == school_id and r.role in ["commander", "deputy"]
        for r in current_user.roles
    )
    if not has_right:
        raise HTTPException(403, "Недостаточно прав")
    query = db.query(SchoolTransactionLog).filter_by(school_id=school_id)
    if operation_type:
        query = query.filter_by(operation_type=operation_type)
    logs = query.order_by(SchoolTransactionLog.created_at.desc()).offset(offset).limit(limit).all()
    return [
        {
            "id": log.id,
            "amount": log.amount,
            "operation_type": log.operation_type,
            "description": log.description,
            "reference_id": log.reference_id,
            "reference_type": log.reference_type,
            "operator_user_id": log.operator_user_id,
            "operator_name": log.operator.username if log.operator else None,
            "created_at": log.created_at.isoformat(),
            "extra_data": log.extra_data
        }
        for log in logs
    ]

def delete_discord_message(webhook_url, message_id):
    """Удаляет сообщение в Discord по его ID."""
    base = webhook_url.rstrip('/')
    url = f"{base}/messages/{message_id}"
    try:
        response = requests.delete(url)
        response.raise_for_status()
        return True
    except Exception as e:
        print(f"Ошибка удаления сообщения в Discord: {e}")
        return False

@app.get("/admin/matches/calculated")
def get_calculated_matches(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not current_user.is_admin:
        raise HTTPException(403, "Доступ запрещён")
    matches = db.query(Match).filter(Match.status != "deleted").all()
    result = []
    for m in matches:
        match_result = db.query(MatchResult).filter(MatchResult.match_id == m.id).first()
        if match_result and match_result.calculated:
            # получаем названия команд
            schools_in_match = db.execute(match_schools.select().where(match_schools.c.match_id == m.id)).mappings().all()
            team1_names = []
            team2_names = []
            for row in schools_in_match:
                school = db.get(School, row["school_id"])
                if school:
                    if row["team"] == 1:
                        team1_names.append(school.name)
                    else:
                        team2_names.append(school.name)
            result.append({
                "id": m.id,
                "date_time": m.date_time.isoformat(),
                "team1": ", ".join(team1_names),
                "team2": ", ".join(team2_names),
                "score": match_result.score,
                "winner_team": match_result.winner_team,
                "result_data": match_result.result_data,
                "referee_school_id": match_result.referee_school_id
            })
    return result

@app.put("/admin/matches/{match_id}/result")
def update_match_result(
        match_id: int,
        req: MatchResultRequest,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    if not current_user.is_admin:
        raise HTTPException(403, "Доступ запрещён")

    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(404, "Матч не найден")

    existing_result = db.query(MatchResult).filter(MatchResult.match_id == match_id).first()
    if not existing_result:
        raise HTTPException(400, "Результат не подан")

    old_data = existing_result.result_data
    new_data = req.dict()
    payment_fields_changed = (
        old_data.get("team1_schools") != new_data.get("team1_schools") or
        old_data.get("team2_schools") != new_data.get("team2_schools") or
        old_data.get("mercenaries") != new_data.get("mercenaries")
    )

    # Откат платежей и логов, если изменились финансовые данные
    if payment_fields_changed and existing_result.payments_snapshot:
        for school_id, amount in existing_result.payments_snapshot.items():
            school = db.get(School, school_id)
            if school:
                school.balance -= amount
        db.query(SchoolTransactionLog).filter(
            SchoolTransactionLog.reference_id == match_id,
            SchoolTransactionLog.reference_type == "match"
        ).delete()

    # Обновляем данные результата
    existing_result.referee_school_id = req.referee_school_id
    existing_result.winner_team = req.winner_team
    existing_result.score = req.score
    existing_result.result_data = new_data
    existing_result.calculated = False
    db.commit()

    # Пересчёт отредактирует старые Discord-сообщения (ID уже есть)
    return calculate_match_result(match_id, db, current_user)

@app.get("/admin/tanks/")
def admin_get_tanks(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not current_user.is_admin:
        raise HTTPException(403, "Доступ запрещён")
    tanks = db.query(Tank).order_by(Tank.id).all()
    return [{
        "id": t.id,
        "name": t.name,
        "price": t.price,
        "rank": t.rank,
        "br": t.br,
        "t_type": t.t_type,
        "nation": t.nation   # <-- добавить эту строку
    } for t in tanks]

@app.post("/admin/tanks/")
def admin_create_tank(req: dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not current_user.is_admin:
        raise HTTPException(403, "Доступ запрещён")
    name = req.get("name")
    price = req.get("price")
    rank = req.get("rank", 1)
    br = req.get("br", 0.0)
    t_type = req.get("t_type", "-")
    nation = req.get("nation")
    if not name or price is None:
        raise HTTPException(400, "Не указано название или цена")
    existing = db.query(Tank).filter(Tank.name == name).first()
    if existing:
        raise HTTPException(400, "Танк с таким названием уже существует")
    tank = Tank(name=name, price=price, rank=rank, br=br, t_type=t_type, nation=nation)
    db.add(tank)
    db.commit()
    db.refresh(tank)
    return {"id": tank.id, "name": tank.name, "price": tank.price, "rank": tank.rank, "br": tank.br, "t_type": tank.t_type, "nation": tank.nation}

@app.put("/admin/tanks/{tank_id}")
def admin_update_tank(tank_id: int, req: dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not current_user.is_admin:
        raise HTTPException(403, "Доступ запрещён")
    tank = db.get(Tank, tank_id)
    if not tank:
        raise HTTPException(404, "Танк не найден")
    if "name" in req:
        existing = db.query(Tank).filter(Tank.name == req["name"], Tank.id != tank_id).first()
        if existing:
            raise HTTPException(400, "Танк с таким названием уже существует")
        tank.name = req["name"]
    if "price" in req:
        tank.price = req["price"]
    if "rank" in req:
        tank.rank = req["rank"]
    if "br" in req:
        tank.br = req["br"]
    if "t_type" in req:
        tank.t_type = req["t_type"]
    if "nation" in req:
        tank.nation = req["nation"]
    db.commit()
    return {"ok": True}

@app.delete("/admin/tanks/{tank_id}")
def admin_delete_tank(
    tank_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if not current_user.is_admin:
        raise HTTPException(403, "Доступ запрещён")
    tank = db.get(Tank, tank_id)
    if not tank:
        raise HTTPException(404, "Танк не найден")
    # Проверяем, используется ли танк в каких-либо таблицах
    # SchoolTank
    in_school = db.query(SchoolTank).filter(SchoolTank.tank_id == tank_id).first()
    if in_school:
        raise HTTPException(400, "Танк есть в инвентаре школ, удаление невозможно")
    # match_tanks
    in_match = db.query(match_tanks).where(match_tanks.c.tank_id == tank_id).first()
    if in_match:
        raise HTTPException(400, "Танк участвовал в матчах, удаление невозможно")
    # ManufacturerTank
    in_manufacturer = db.query(ManufacturerTank).filter(ManufacturerTank.tank_id == tank_id).first()
    if in_manufacturer:
        raise HTTPException(400, "Танк есть в списке производителя какой-то школы, удалите его сначала оттуда")
    # ImportTank
    in_import = db.query(ImportTank).filter(ImportTank.tank_id == tank_id).first()
    if in_import:
        raise HTTPException(400, "Танк используется в импортах, удаление невозможно")
    # TankUpgrade
    in_upgrade = db.query(TankUpgrade).filter(
        (TankUpgrade.from_tank_id == tank_id) | (TankUpgrade.to_tank_id == tank_id)
    ).first()
    if in_upgrade:
        raise HTTPException(400, "Танк задействован в дереве улучшений, удаление невозможно")
    db.delete(tank)
    db.commit()
    return {"ok": True}

@app.get("/admin/schools/{school_id}/manufacturer")
def admin_get_manufacturer(
    school_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if not current_user.is_admin:
        raise HTTPException(403, "Доступ запрещён")
    school = db.get(School, school_id)
    if not school:
        raise HTTPException(404, "Школа не найдена")
    tanks = []
    for mt in school.manufacturer_tanks:
        tanks.append({
            "id": mt.tank.id,
            "name": mt.tank.name,
            "price": mt.tank.price,
            "rank": mt.tank.rank,
            "br": mt.tank.br,
            "t_type": mt.tank.t_type
        })
    return tanks

@app.post("/admin/schools/{school_id}/manufacturer")
def admin_add_manufacturer_tank(
    school_id: int,
    req: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if not current_user.is_admin:
        raise HTTPException(403, "Доступ запрещён")
    tank_id = req.get("tank_id")
    if not tank_id:
        raise HTTPException(400, "Не указан tank_id")
    school = db.get(School, school_id)
    if not school:
        raise HTTPException(404, "Школа не найдена")
    tank = db.get(Tank, tank_id)
    if not tank:
        raise HTTPException(404, "Танк не найден")
    exists = db.query(ManufacturerTank).filter_by(school_id=school_id, tank_id=tank_id).first()
    if exists:
        raise HTTPException(400, "Танк уже есть в производителе")
    db.add(ManufacturerTank(school_id=school_id, tank_id=tank_id))
    db.commit()
    return {"ok": True}

@app.delete("/admin/schools/{school_id}/manufacturer/{tank_id}")
def admin_remove_manufacturer_tank(
    school_id: int,
    tank_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if not current_user.is_admin:
        raise HTTPException(403, "Доступ запрещён")
    record = db.query(ManufacturerTank).filter_by(school_id=school_id, tank_id=tank_id).first()
    if not record:
        raise HTTPException(404, "Танк не найден в производителе")
    db.delete(record)
    db.commit()
    return {"ok": True}

def send_match_message(match: Match, db: Session) -> str | None:
    """Формирует и отправляет сообщение о матче в Discord, возвращает ID сообщения."""
    webhook_matches = os.getenv("DISCORD_WEBHOOK_MATCHES")
    if not webhook_matches:
        return None

    # Формируем содержимое сообщения
    content = generate_match_message(match, db)
    return send_discord_message(webhook_matches, content)


def edit_match_message(match: Match, db: Session) -> bool:
    """Редактирует существующее сообщение о матче в Discord."""
    webhook_matches = os.getenv("DISCORD_WEBHOOK_MATCHES")
    if not webhook_matches or not match.discord_match_message_id:
        return False
    content = generate_match_message(match, db)
    return edit_discord_message(webhook_matches, match.discord_match_message_id, content)


def delete_match_message(match: Match) -> bool:
    """Удаляет сообщение о матче в Discord."""
    webhook_matches = os.getenv("DISCORD_WEBHOOK_MATCHES")
    if not webhook_matches or not match.discord_match_message_id:
        return False
    return delete_discord_message(webhook_matches, match.discord_match_message_id)


def generate_match_message(match: Match, db: Session) -> str:
    # Получаем школы из связи many-to-many
    schools_in_match = db.execute(
        match_schools.select().where(match_schools.c.match_id == match.id)
    ).mappings().all()
    team1_schools = []  # список кортежей (school, mention)
    team2_schools = []
    for row in schools_in_match:
        school = db.get(School, row["school_id"])
        if not school:
            continue
        if school.discord_role_id:
            mention = f"<@&{school.discord_role_id}>"
        else:
            mention = f"**{school.name}**"
        if row["team"] == 1:
            team1_schools.append((school, mention))
        else:
            team2_schools.append((school, mention))

    # Группируем танки по школам
    tank_rows = db.execute(
        match_tanks.select().where(match_tanks.c.match_id == match.id)
    ).mappings().all()
    tanks_by_school = {}
    for row in tank_rows:
        school = db.get(School, row["school_id"])
        tank = db.get(Tank, row["tank_id"])
        if not school or not tank:
            continue
        if school.name not in tanks_by_school:
            tanks_by_school[school.name] = []
        for _ in range(row["quantity"]):
            tanks_by_school[school.name].append(tank.name)

    def build_team_text(team_schools):
        lines = []
        for idx, (school, _) in enumerate(team_schools):
            lines.append(school.name)
            tank_list = tanks_by_school.get(school.name, [])
            for tank in tank_list:
                lines.append(tank)
            if idx != len(team_schools) - 1:
                lines.append("")
        return "\n".join(lines)

    # --- Обработка даты и времени ---
    dt = match.date_time
    # Приводим к UTC
    if dt.tzinfo is None:
        dt_utc = pytz.UTC.localize(dt)
    else:
        dt_utc = dt.astimezone(pytz.UTC)

    timestamp = int(dt_utc.timestamp())

    # Переводим в МСК для ручного отображения
    msk = pytz.timezone('Europe/Moscow')
    dt_msk = dt_utc.astimezone(msk)

    # День недели на русском
    eng_weekday = dt_msk.strftime("%A")
    ru_weekday = DAYS_RU.get(eng_weekday, eng_weekday)
    date_dmy = dt_msk.strftime("%d.%m.%Y")
    time_hmsk = dt_msk.strftime("%H:%M")
    msk_part = f"{ru_weekday}, {date_dmy} - {time_hmsk} МСК"

    # Локальное время пользователя через Discord-теги
    local_full = f"<t:{timestamp}:F>"  # полная дата/время в локали пользователя
    local_relative = f"<t:{timestamp}:R>"  # относительное время

    date_line = f"{msk_part} - {local_full} ({local_relative})"

    # Формируем шапку
    team1_mentions = [m for _, m in team1_schools]
    team2_mentions = [m for _, m in team2_schools]
    header = f"{' vs '.join(team1_mentions)} vs {' vs '.join(team2_mentions)}\n"
    header += f"{date_line}\n"
    header += f"{match.mode} - Bo{match.format}\n"
    header += f"Карты: {match.map_selection or '—'}\n"
    header += f"Спец.правила: {match.special_rules or '—'}\n\n"

    team1_text = build_team_text(team1_schools)
    team2_text = build_team_text(team2_schools)

    body = header + team1_text + "\n\n--- vs. ---\n\n" + team2_text
    return body

def calculate_team_strength(school_ids, db):
    """Возвращает средний рейтинг школ в команде"""
    ratings = []
    for sid in school_ids:
        school = db.query(School).filter(School.id == sid).first()
        if school:
            ratings.append(school.rating)
    return sum(ratings) / len(ratings) if ratings else 1500


def calculate_team_avg_br(school_instances):
    """Средний БР танков школы на момент матча (данные из match.tanks)"""
    # Нужно передавать список танков каждой школы из матча
    # Упрощённо: берём средний БР всех танков, участвовавших в матче
    brs = []
    for school in school_instances:
        for tank in school.tanks:
            for _ in range(tank.quantity):
                brs.append(tank.br)
    return sum(brs) / len(brs) if brs else 5.0


def expected_score(rating_self, rating_opp, br_self, br_opp):
    """Ожидаемый результат с учётом разницы рейтингов и силы танков"""
    rating_diff = rating_opp - rating_self
    elo_prob = 1 / (1 + 10 ** (rating_diff / 400))
    # сила танков: чем выше БР, тем сильнее
    br_ratio = br_self / (br_self + br_opp) if (br_self + br_opp) > 0 else 0.5
    # комбинируем: 60% Elo, 40% танки
    return 0.6 * elo_prob + 0.4 * br_ratio


def update_ratings_for_match(match: Match, result: MatchResult, db: Session):
    K = 32
    score_map = {"3:0": 1.2, "3:1": 1.1, "3:2": 1.0}
    score_coef = score_map.get(result.score, 1.0)
    winner_team = result.winner_team

    # Получаем ID школ из match_schools
    team1_ids = []
    team2_ids = []
    schools_in_match = db.execute(
        match_schools.select().where(match_schools.c.match_id == match.id)
    ).mappings().all()
    for row in schools_in_match:
        if row["team"] == 1:
            team1_ids.append(row["school_id"])
        else:
            team2_ids.append(row["school_id"])

    # Получаем объекты школ
    team1_schools = [db.get(School, sid) for sid in team1_ids if db.get(School, sid)]
    team2_schools = [db.get(School, sid) for sid in team2_ids if db.get(School, sid)]

    # Получаем все танки матча
    tanks_rows = db.execute(
        match_tanks.select().where(match_tanks.c.match_id == match.id)
    ).mappings().all()
    # Группируем по school_id
    tanks_by_school = {}
    for t in tanks_rows:
        school_id = t["school_id"]
        tank = db.get(Tank, t["tank_id"])
        if tank:
            tanks_by_school.setdefault(school_id, []).extend([tank.br] * t["quantity"])

    # Вычисляем средний БР для каждой школы
    school_br = {}
    for school in team1_schools + team2_schools:
        br_list = tanks_by_school.get(school.id, [])
        school_br[school.id] = sum(br_list) / len(br_list) if br_list else 5.0

    # Средние рейтинги команд
    team1_ratings = [s.rating for s in team1_schools]
    team2_ratings = [s.rating for s in team2_schools]
    team1_strength = sum(team1_ratings) / len(team1_ratings) if team1_ratings else 1500
    team2_strength = sum(team2_ratings) / len(team2_ratings) if team2_ratings else 1500

    # Средние БР команд
    team1_br = sum(school_br.get(s.id, 5.0) for s in team1_schools) / len(team1_schools) if team1_schools else 5.0
    team2_br = sum(school_br.get(s.id, 5.0) for s in team2_schools) / len(team2_schools) if team2_schools else 5.0

    for school in team1_schools + team2_schools:
        # Определяем, победила ли школа
        if (winner_team == 1 and school in team1_schools) or (winner_team == 2 and school in team2_schools):
            real = 1
            mult = score_coef
        else:
            real = 0
            mult = 1 / score_coef if score_coef != 0 else 1

        # Параметры оппонента
        if school in team1_schools:
            rating_opp = team2_strength
            br_opp = team2_br
        else:
            rating_opp = team1_strength
            br_opp = team1_br

        expected = expected_score(school.rating, rating_opp, school_br[school.id], br_opp)

        # Вес внутри команды
        teammates = team1_schools if school in team1_schools else team2_schools
        if len(teammates) > 1:
            mates_ratings = [s.rating for s in teammates]
            min_r = min(mates_ratings)
            max_r = max(mates_ratings)
            if max_r > min_r:
                weight = 0.8 + 0.4 * (max_r - school.rating) / (max_r - min_r)
            else:
                weight = 1.0
        else:
            weight = 1.0

        delta = K * (real - expected) * mult * weight
        school.rating += delta

        # Обновление статистики побед/поражений и серий
        if real == 1:
            school.wins += 1
            school.current_streak += 1
            if school.current_streak > school.max_streak:
                school.max_streak = school.current_streak
        else:
            school.losses += 1
            school.current_streak = 0

        db.add(school)
    db.commit()


@app.delete("/import/apply/{tank_import_id}")
def cancel_import_application(
        tank_import_id: int,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    # Проверяем права
    if not current_user.roles:
        raise HTTPException(403, "У вас нет прав на отзыв заявки")
    school_id = current_user.roles[0].school_id

    # Находим танк в импорте
    import_tank = db.query(ImportTank).filter(ImportTank.id == tank_import_id).first()
    if not import_tank:
        raise HTTPException(404, "Танк в импорте не найден")

    event = import_tank.event
    # Импорт должен быть активен и ещё не разыгран
    if not event.is_active or event.is_drawn:
        raise HTTPException(400, "Импорт уже завершён или разыгран, отзыв невозможен")

    # Проверяем, что приём заявок ещё идёт
    now_utc = datetime.now(pytz.UTC)
    start_utc = pytz.UTC.localize(event.start_date)
    end_utc = pytz.UTC.localize(event.end_date)
    if now_utc < start_utc or now_utc > end_utc:
        raise HTTPException(400, "Время приёма заявок уже вышло или ещё не началось")

    # Находим заявку этой школы на этот танк
    application = db.query(ImportApplication).filter(
        ImportApplication.event_id == event.id,
        ImportApplication.school_id == school_id,
        ImportApplication.tank_id == import_tank.tank_id
    ).first()
    if not application:
        raise HTTPException(404, "Заявка не найдена")

    # Удаляем заявку
    db.delete(application)
    db.commit()
    return {"ok": True, "message": "Заявка отозвана"}

_school_locks = defaultdict(Lock)

def get_school_lock(school_id: int) -> Lock:
    return _school_locks[school_id]