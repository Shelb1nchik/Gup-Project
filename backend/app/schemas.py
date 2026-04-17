from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

# --- Существующие схемы ---
class MatchTankItem(BaseModel):
    school_id: int
    tank_id: int
    quantity: int

class MatchCreateRequest(BaseModel):
    team1_school_ids: List[int]
    team2_school_ids: List[int]
    date_time: datetime
    mode: str
    format: int
    special_rules: Optional[str] = "-"
    map_selection: Optional[str] = "-"
    tanks: List[MatchTankItem]

class MatchTankOut(BaseModel):
    school_id: int
    tank_id: int
    quantity: int
    name: str
    br: float | None = None

class SchoolInMatch(BaseModel):
    id: int
    name: str
    tanks: List[MatchTankOut] = []

class MatchResponse(BaseModel):
    id: int
    date_time: datetime
    team1: List[SchoolInMatch] = []
    team2: List[SchoolInMatch] = []
    mode: str
    format: str
    special_rules: str
    map_selection: str
    tanks: List[MatchTankOut] = []
    calculated: bool = False

    class Config:
        from_attributes = True

class TankUpdateItem(BaseModel):
    school_id: int
    tank_id: int
    quantity: int

# Alias для совместимости с именем из main.py
MatchTankUpdate = TankUpdateItem

class MatchUpdateRequest(BaseModel):
    team1_school_ids: List[int]
    team2_school_ids: List[int]
    date_time: datetime
    mode: str
    format: int
    special_rules: str
    map_selection: str
    tanks: List[TankUpdateItem]

class TankDeathItem(BaseModel):
    tank_id: int
    deaths: int

class SchoolResultItem(BaseModel):
    school_id: int
    bonuses: int
    penalties: int
    tank_deaths: List[TankDeathItem]

class MercenaryItem(BaseModel):
    school_id: int
    activity: str
    team: int

class MatchResultRequest(BaseModel):
    referee_school_id: Optional[int] = None
    winner_team: int
    score: str
    team1_schools: List[SchoolResultItem]
    team2_schools: List[SchoolResultItem]
    mercenaries: List[MercenaryItem] = []

class SchoolOut(BaseModel):
    id: int
    name: str
    balance: int
    rating: int = 1500
    wins: int = 0
    losses: int = 0

    class Config:
        from_attributes = True

class UserRegister(BaseModel):
    username: str
    password: str
    confirm_password: str

class UserLogin(BaseModel):
    username: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str

class UserOut(BaseModel):
    id: int
    username: str
    roles: list[dict]

# --- Добавляем схемы, которые были в main.py ---
class BuyItem(BaseModel):
    tank_id: int
    quantity: int

class BuyRequest(BaseModel):
    school_id: int
    items: List[BuyItem]

class TransferRequest(BaseModel):
    from_school_id: int
    to_school_id: int
    amount: int