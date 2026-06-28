"""APScheduler job definitions — daily chip data collection."""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.core.database import SessionLocal

logger = logging.getLogger(__name__)

_CST = timezone(timedelta(hours=8))


def _today_cst() -> date:
    return datetime.now(_CST).date()


def _is_trading_day(d: date) -> bool:
    db = SessionLocal()
    try:
        from app.collectors.trading_calendar import TradingCalendarCollector
        cal = TradingCalendarCollector(db)
        return cal.is_trading_day(d)
    finally:
        db.close()


# ── Job functions ─────────────────────────────────────────────────────────

def job_collect_stocks() -> None:
    """Refresh stock list (run once daily, not trading-day gated)."""
    db = SessionLocal()
    try:
        from app.collectors.twse_stocks import StockListCollector
        c = StockListCollector(db)
        today = _today_cst()
        count = c.collect(today)
        c.supplement_from_sinopac()
        logger.info("[job_collect_stocks] %d stocks refreshed", count)
    except Exception as e:
        logger.error("[job_collect_stocks] error: %s", e, exc_info=True)
    finally:
        db.close()


def job_daily_collect() -> None:
    """Main daily collection: institutional / margin / futures OI."""
    today = _today_cst()
    if not _is_trading_day(today):
        logger.info("[job_daily_collect] %s is not a trading day, skipping", today)
        return

    db = SessionLocal()
    try:
        from app.collectors.twse_institutional import InstitutionalCollector
        from app.collectors.twse_margin import MarginCollector
        from app.collectors.taifex_futures import FuturesOICollector

        results: dict[str, int] = {}

        for Cls in (InstitutionalCollector, MarginCollector, FuturesOICollector):
            col = Cls(db)
            try:
                results[col.name] = col.collect(today)
            except Exception as e:
                logger.error("[job_daily_collect] %s failed: %s", col.name, e)
                results[col.name] = -1

        logger.info("[job_daily_collect] %s results: %s", today, results)
    finally:
        db.close()


def job_broker_chips() -> None:
    """Broker chips — 上市(TWSE) + 上櫃(TPEx)，各取機構動能前 200 支。"""
    today = _today_cst()
    if not _is_trading_day(today):
        return

    db = SessionLocal()
    try:
        from app.collectors.twse_broker_chips import BrokerChipsCollector
        from app.collectors.tpex_broker_chips import TpexBrokerChipsCollector
        from app.models.raw import RawInstitutional
        from sqlalchemy import func, desc

        # 上市：法人動能前 200
        twse_top = (
            db.query(RawInstitutional.stock_id)
            .filter(RawInstitutional.date == today)
            .order_by(desc(func.abs(
                RawInstitutional.foreign_buy - RawInstitutional.foreign_sell
                + RawInstitutional.trust_buy - RawInstitutional.trust_sell
            )))
            .limit(200)
            .all()
        )
        twse_ids = [r.stock_id for r in twse_top]
        twse_count = BrokerChipsCollector(db).collect_stocks(today, twse_ids)

        # 上櫃：同樣策略，限 100 支（TPEx 較慢）
        otc_top = (
            db.query(RawInstitutional.stock_id)
            .filter(RawInstitutional.date == today)
            .order_by(desc(func.abs(
                RawInstitutional.foreign_buy - RawInstitutional.foreign_sell
                + RawInstitutional.trust_buy - RawInstitutional.trust_sell
            )))
            .limit(100)
            .all()
        )
        otc_ids = [r.stock_id for r in otc_top]
        otc_count = TpexBrokerChipsCollector(db).collect_stocks(today, otc_ids)

        logger.info("[job_broker_chips] twse=%d rows/%d stocks  otc=%d rows/%d stocks",
                    twse_count, len(twse_ids), otc_count, len(otc_ids))
    finally:
        db.close()


def job_process_chip() -> None:
    """Run ChipProcessor after daily collection to build processed_chip."""
    today = _today_cst()
    if not _is_trading_day(today):
        return
    db = SessionLocal()
    try:
        from app.processors.chip_processor import ChipProcessor
        count = ChipProcessor(db).process(today)
        logger.info("[job_process_chip] %d rows processed for %s", count, today)
    except Exception as e:
        logger.error("[job_process_chip] error: %s", e, exc_info=True)
    finally:
        db.close()


def job_generate_report() -> None:
    """Generate daily Excel report after chip processing."""
    today = _today_cst()
    if not _is_trading_day(today):
        return
    db = SessionLocal()
    try:
        from app.reporters.chip_reporter import ChipReporter
        fpath = ChipReporter(db).generate(today)
        logger.info("[job_generate_report] saved: %s", fpath)
    except Exception as e:
        logger.error("[job_generate_report] error: %s", e, exc_info=True)
    finally:
        db.close()


def job_collect_options() -> None:
    """選擇權每日採集 — TAIFEX OpenAPI（chain / institutional / large_traders / P/C比）。"""
    today = _today_cst()
    if not _is_trading_day(today):
        return
    db = SessionLocal()
    try:
        from app.collectors.taifex_options import TaifexOptionsCollector
        results = TaifexOptionsCollector(db).collect(today)
        logger.info("[job_collect_options] %s results: %s", today, results)
    except Exception as e:
        logger.error("[job_collect_options] error: %s", e, exc_info=True)
    finally:
        db.close()


def job_fill_calendar() -> None:
    """Ensure trading calendar covers current + next year."""
    db = SessionLocal()
    try:
        from app.collectors.trading_calendar import TradingCalendarCollector
        col = TradingCalendarCollector(db)
        today = _today_cst()
        for year in (today.year, today.year + 1):
            count = col.fill_year(year)
            logger.info("[job_fill_calendar] year=%d, %d days", year, count)
    finally:
        db.close()


# ── Scheduler factory ─────────────────────────────────────────────────────

def create_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="Asia/Taipei")

    # Stock list refresh — every day 09:00 CST
    scheduler.add_job(job_collect_stocks, CronTrigger(hour=9, minute=0, timezone="Asia/Taipei"),
                      id="collect_stocks", replace_existing=True)

    # Main daily collection — 16:35 CST (after TWSE closes + publishes)
    scheduler.add_job(job_daily_collect, CronTrigger(hour=16, minute=35, timezone="Asia/Taipei"),
                      id="daily_collect", replace_existing=True)

    # Broker chips — 17:00 CST (after main collection)
    scheduler.add_job(job_broker_chips, CronTrigger(hour=17, minute=0, timezone="Asia/Taipei"),
                      id="broker_chips", replace_existing=True)

    # Options collect — 17:05 CST (TAIFEX OpenAPI 盤後約 17:00 更新)
    scheduler.add_job(job_collect_options, CronTrigger(hour=17, minute=5, timezone="Asia/Taipei"),
                      id="collect_options", replace_existing=True)

    # Chip processor — 17:15 CST (after broker chips, build processed_chip)
    scheduler.add_job(job_process_chip, CronTrigger(hour=17, minute=15, timezone="Asia/Taipei"),
                      id="process_chip", replace_existing=True)

    # Daily report — 17:30 CST (after process_chip)
    scheduler.add_job(job_generate_report, CronTrigger(hour=17, minute=30, timezone="Asia/Taipei"),
                      id="generate_report", replace_existing=True)

    # Trading calendar refresh — 1st of each month 08:00 CST
    scheduler.add_job(job_fill_calendar, CronTrigger(day=1, hour=8, minute=0, timezone="Asia/Taipei"),
                      id="fill_calendar", replace_existing=True)

    return scheduler
