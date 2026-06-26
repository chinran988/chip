"""CHIP Platform — FastAPI application entry point (port 8001)."""
from __future__ import annotations

import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Resolve .env from backend/ directory regardless of cwd
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    os.environ.setdefault("ENV_FILE", str(_env_path))

from app.core.config import settings
from app.core.database import init_db
from app.api.v1.health import router as health_router
from app.api.v1.stocks import router as stocks_router
from app.api.v1.admin import router as admin_router
from app.api.v1.chip import router as chip_router
from app.api.v1.futures import router as futures_router
from app.api.v1.reports import router as reports_router

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(settings.logs_dir / "chip.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("CHIP Platform starting on port %d", settings.PORT)
    init_db()
    logger.info("chip.db initialized: %s", settings.db_path)

    from app.scheduler.jobs import create_scheduler
    scheduler = create_scheduler()
    scheduler.start()
    logger.info("Scheduler started — %d jobs", len(scheduler.get_jobs()))

    yield

    scheduler.shutdown(wait=False)
    logger.info("CHIP Platform stopped")


app = FastAPI(
    title="CHIP Platform API",
    description="Taiwan Institutional Chip Intelligence Platform",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(stocks_router)
app.include_router(chip_router)
app.include_router(futures_router)
app.include_router(reports_router)
app.include_router(admin_router)


@app.post("/api/restart")
async def restart():
    import asyncio
    async def _bye():
        await asyncio.sleep(0.3)
        logger.info("收到 /api/restart — exit(42) 交由 supervisor 重啟")
        os._exit(42)
    asyncio.create_task(_bye())
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=settings.DEBUG)
