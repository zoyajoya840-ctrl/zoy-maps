import os
from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, DateTime, ForeignKey, event
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from sqlalchemy.pool import NullPool
from datetime import datetime, timezone

os.makedirs("data", exist_ok=True)
SQLALCHEMY_DATABASE_URL = os.getenv("ZOY_DB_URL", "sqlite:///./data/zoy_maps_v2.db")

# NullPool avoids QueuePool exhaustion under concurrent Leaflet tile requests
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30},
    poolclass=NullPool,
)


@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA synchronous=NORMAL;")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(64), unique=True, index=True, nullable=False)
    project_name = Column(String(120), nullable=False)
    owner_email = Column(String(120), nullable=False)
    plan = Column(String(32), default="pro")
    rate_limit_per_min = Column(Integer, default=300)
    monthly_quota = Column(Integer, default=250000)
    requests_used = Column(Integer, default=0)
    wallet_balance_inr = Column(Float, default=0.0)
    is_active = Column(Boolean, default=True)
    allowed_origins = Column(String(500), default="*")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    logs = relationship("UsageLog", back_populates="api_key_obj", cascade="all, delete-orphan")


class UsageLog(Base):
    __tablename__ = "usage_logs"

    id = Column(Integer, primary_key=True, index=True)
    api_key_id = Column(Integer, ForeignKey("api_keys.id"), nullable=False)
    endpoint = Column(String(120), nullable=False)
    method = Column(String(10), default="GET")
    status_code = Column(Integer, default=200)
    latency_ms = Column(Float, default=0.0)
    query_summary = Column(String(255), default="")
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    api_key_obj = relationship("ApiKey", back_populates="logs")


class CustomPlace(Base):
    __tablename__ = "custom_places"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), index=True, nullable=False)
    category = Column(String(80), default="landmark")
    address = Column(String(400), nullable=False)
    city = Column(String(100), default="Jaipur")
    state = Column(String(100), default="Rajasthan")
    lat = Column(Float, nullable=False)
    lng = Column(Float, nullable=False)
    plus_code = Column(String(32), index=True, default="")
    verified = Column(Boolean, default=True)
    contributed_by = Column(String(120), default="Zoy Maps Core")
    rating = Column(Float, default=4.8)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class BillingTransaction(Base):
    __tablename__ = "billing_transactions"

    id = Column(Integer, primary_key=True, index=True)
    api_key_str = Column(String(64), index=True, nullable=False)
    plan_purchased = Column(String(32), nullable=False)
    amount_inr = Column(Float, nullable=False)
    payment_ref = Column(String(120), unique=True, nullable=False)
    status = Column(String(32), default="paid")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


def init_db():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
