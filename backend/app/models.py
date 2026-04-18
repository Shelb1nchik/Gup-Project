from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime, Table, JSON, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_admin = Column(Boolean, default=False)
    roles = relationship("UserRole", back_populates="user")


class UserRole(Base):
    __tablename__ = "user_roles"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    school_id = Column(Integer, ForeignKey("schools.id"), nullable=False)
    role = Column(String, nullable=False)  # "commander" или "deputy"

    user = relationship("User", back_populates="roles")
    school = relationship("School")

# ------------------------ Школы ------------------------
class School(Base):
    __tablename__ = "schools"

    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    balance = Column(Integer, default=0)

    background_path = Column(String, nullable=True)

    tanks = relationship("SchoolTank", back_populates="school")
    manufacturer_tanks = relationship("ManufacturerTank", back_populates="school")
    discord_role_id = Column(String, nullable=True)

    rating = Column(Integer, default=1500, nullable=False)
    wins = Column(Integer, default=0, nullable=False)
    losses = Column(Integer, default=0, nullable=False)
    current_streak = Column(Integer, default=0)  # текущая серия побед
    max_streak = Column(Integer, default=0)


# ------------------------ Танки ------------------------
class Tank(Base):
    __tablename__ = "tanks"
    id = Column(Integer, primary_key=True)
    name = Column(String)
    br = Column(Float)
    price = Column(Integer)
    rank = Column(Integer)
    t_type = Column(String)

    manufacturer_schools = relationship("ManufacturerTank", back_populates="tank")
    school_tanks = relationship("SchoolTank", back_populates="tank")


# ------------------------ Танки конкретной школы ------------------------
class SchoolTank(Base):
    __tablename__ = "school_tanks"

    id = Column(Integer, primary_key=True)
    school_id = Column(Integer, ForeignKey("schools.id"))
    tank_id = Column(Integer, ForeignKey("tanks.id"))
    quantity = Column(Integer, default=0)

    school = relationship("School", back_populates="tanks")
    tank = relationship("Tank")


# ------------------------ Производитель → школа ------------------------
class ManufacturerTank(Base):
    __tablename__ = "manufacturer_tanks"

    id = Column(Integer, primary_key=True)
    school_id = Column(Integer, ForeignKey("schools.id"))
    tank_id = Column(Integer, ForeignKey("tanks.id"))

    school = relationship("School", back_populates="manufacturer_tanks")
    tank = relationship("Tank")


match_schools = Table(
    "match_schools", Base.metadata,
    Column("match_id", Integer, ForeignKey("matches.id")),
    Column("school_id", Integer, ForeignKey("schools.id")),
    Column("team", Integer),
)

match_tanks = Table(
    "match_tanks", Base.metadata,
    Column("match_id", Integer, ForeignKey("matches.id")),
    Column("school_id", Integer, ForeignKey("schools.id")),
    Column("tank_id", Integer, ForeignKey("tanks.id")),
    Column("quantity", Integer),
)

class Match(Base):
    __tablename__ = "matches"
    id = Column(Integer, primary_key=True)
    date_time = Column(DateTime)
    mode = Column(String)
    format = Column(String)
    special_rules = Column(String)
    map_selection = Column(String)
    status = Column(String, default="active")
    discord_match_message_id = Column(String, nullable=True)

    # Связь Many-to-Many только с School
    schools = relationship(
        "School",
        secondary=match_schools,
        backref="matches"
    )

class MatchResult(Base):
    __tablename__ = "match_results"
    id = Column(Integer, primary_key=True)
    match_id = Column(Integer, ForeignKey("matches.id"), unique=True, nullable=False)
    referee_school_id = Column(Integer, ForeignKey("schools.id"), nullable=True)
    winner_team = Column(Integer, nullable=False)
    score = Column(String, nullable=False)
    result_data = Column(JSON, nullable=False)   # храним полный JSON от фронта
    calculated = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    match = relationship("Match", backref="result")
    referee_school = relationship("School")
    payments_snapshot = Column(JSON, nullable=True)
    discord_result_message_id = Column(String, nullable=True)  # детальный отчёт (results)
    discord_payment_message_id = Column(String, nullable=True)

class TankUpgrade(Base):
    __tablename__ = "tank_upgrades"
    id = Column(Integer, primary_key=True)
    from_tank_id = Column(Integer, ForeignKey("tanks.id"), nullable=False)
    to_tank_id = Column(Integer, ForeignKey("tanks.id"), nullable=False)
    # стоимость может быть вычислена динамически, но можно хранить явно
    # cost = Column(Integer, nullable=True)  # если NULL, вычисляем по формуле

    from_tank = relationship("Tank", foreign_keys=[from_tank_id])
    to_tank = relationship("Tank", foreign_keys=[to_tank_id])
    is_direct = Column(Boolean, default=True)


class ImportEvent(Base):
    __tablename__ = "import_events"
    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    display_date = Column(DateTime, nullable=False)   # когда импорт появляется
    start_date = Column(DateTime, nullable=False)    # начало приёма заявок
    end_date = Column(DateTime, nullable=False)      # окончание приёма заявок
    min_br = Column(Float, default=0.3)
    max_br = Column(Float, default=7.7)
    tanks_count = Column(Integer, default=8)
    is_active = Column(Boolean, default=True)
    is_drawn = Column(Boolean, default=False)

    tanks = relationship("ImportTank", back_populates="event")
    applications = relationship("ImportApplication", back_populates="event")

class ImportTank(Base):
    __tablename__ = "import_tanks"
    id = Column(Integer, primary_key=True)
    event_id = Column(Integer, ForeignKey("import_events.id"), nullable=False)
    tank_id = Column(Integer, ForeignKey("tanks.id"), nullable=False)
    price = Column(Integer, nullable=False)
    winner_school_id = Column(Integer, ForeignKey("schools.id"), nullable=True)

    event = relationship("ImportEvent", back_populates="tanks")
    tank = relationship("Tank")
    winner_school = relationship("School")

class ImportApplication(Base):
    __tablename__ = "import_applications"
    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(Integer, ForeignKey("import_events.id"))
    school_id = Column(Integer, ForeignKey("schools.id"))
    tank_id = Column(Integer, ForeignKey("tanks.id"))
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    applied_at = Column(DateTime, default=datetime.utcnow)   # вместо created_at

    event = relationship("ImportEvent", back_populates="applications")
    school = relationship("School")
    tank = relationship("Tank")
    user = relationship("User")

class SchoolTransactionLog(Base):
    __tablename__ = "school_transaction_logs"

    id = Column(Integer, primary_key=True)
    school_id = Column(Integer, ForeignKey("schools.id"), nullable=False)
    amount = Column(Integer, nullable=False)          # положительное или отрицательное
    operation_type = Column(String, nullable=False)   # match_reward, tank_purchase, transfer_sent и т.д.
    description = Column(String, nullable=True)       # краткое описание для отображения
    reference_id = Column(Integer, nullable=True)     # id матча, перевода, покупки и т.п.
    reference_type = Column(String, nullable=True)    # 'match', 'transfer', 'purchase', 'upgrade', ...
    operator_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    extra_data = Column(JSON, nullable=True)          # дополнительные детали (команды, счёт, список танков)

    school = relationship("School", backref="logs")
    operator = relationship("User")