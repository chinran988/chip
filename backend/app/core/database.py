from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from app.core.config import settings


engine = create_engine(
    settings.db_url,
    connect_args={"check_same_thread": False},
    pool_pre_ping=True,
)


# Enable WAL mode and foreign keys on every new connection
@event.listens_for(engine, "connect")
def _on_connect(dbapi_conn, _):
    dbapi_conn.execute("PRAGMA journal_mode=WAL")
    dbapi_conn.execute("PRAGMA synchronous=NORMAL")
    dbapi_conn.execute("PRAGMA foreign_keys=ON")
    dbapi_conn.execute("PRAGMA cache_size=-64000")  # 64 MB page cache


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def _migrate() -> None:
    """SQLite schema migrations — idempotent, safe to call on every startup."""
    from sqlalchemy import text
    with engine.connect() as conn:
        cols = {
            row[1]
            for row in conn.execute(text("PRAGMA table_info(raw_options_chain)")).fetchall()
        }
        if "trading_session" not in cols:
            bak = conn.execute(text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='_chain_bak'"
            )).fetchone()
            if bak:
                conn.execute(text("DROP TABLE _chain_bak"))
            conn.execute(text("ALTER TABLE raw_options_chain RENAME TO _chain_bak"))
            conn.commit()

    from app.models import reference, raw  # noqa: F401 — registers all models
    Base.metadata.create_all(bind=engine)

    with engine.connect() as conn:
        bak = conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='_chain_bak'"
        )).fetchone()
        if bak:
            conn.execute(text("""
                INSERT OR IGNORE INTO raw_options_chain
                    (date, contract, expiry, strike, call_put, trading_session,
                     open, high, low, close, volume, settlement_price,
                     open_interest, best_bid, best_ask, created_at)
                SELECT date, contract, expiry, strike, call_put, '一般',
                       open, high, low, close, volume, settlement_price,
                       open_interest, best_bid, best_ask, created_at
                FROM _chain_bak
            """))
            conn.execute(text("DROP TABLE _chain_bak"))
            conn.commit()


def init_db() -> None:
    _migrate()
    from app.models import reference, raw  # noqa: F401 — registers all models
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
