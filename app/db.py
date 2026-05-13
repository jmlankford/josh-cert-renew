import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

DATA_DIR = "/app/data"
os.makedirs(DATA_DIR, exist_ok=True)

DATABASE_URL = f"sqlite:///{DATA_DIR}/certmanager.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from app.models import domain, credential, history  # noqa: F401 – side-effect imports register ORM classes
    Base.metadata.create_all(bind=engine)
