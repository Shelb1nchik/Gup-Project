from sqlalchemy import create_engine, NullPool
from sqlalchemy.orm import sessionmaker, declarative_base

SQLALCHEMY_DATABASE_URL = "sqlite:///./gup.db?check_same_thread=False&timeout=20"

engine = create_engine(SQLALCHEMY_DATABASE_URL, poolclass=NullPool, connect_args={"timeout": 20})

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()