from datetime import datetime, timezone, timedelta
from fastapi import APIRouter
from sqlalchemy import text
from app.core.database import SessionLocal
from app.core.config import settings

router = APIRouter(tags=["health"])
_CST = timezone(timedelta(hours=8))


@router.get("/api/health")
def health():
    db = SessionLocal()
    try:
        # Last collection timestamps
        last = {}
        for tbl in ("raw_institutional", "raw_margin", "raw_futures_oi", "raw_broker_chips"):
            row = db.execute(text(f"SELECT MAX(date) FROM {tbl}")).scalar()
            last[tbl] = str(row) if row else None

        # Stock count
        stock_count = db.execute(text("SELECT COUNT(*) FROM stocks")).scalar()
    finally:
        db.close()

    return {
        "status": "ok",
        "server_time_cst": datetime.now(_CST).isoformat(),
        "port": settings.PORT,
        "last_collection": last,
        "stock_count": stock_count,
    }
