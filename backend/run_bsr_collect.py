"""BSR 買賣日報表全量採集 — ddddocr 自動過 CAPTCHA，30±5 秒/支。

用法：
    python run_bsr_collect.py [--date YYYY-MM-DD] [--resume]

--date   採集日期（預設今日台北時間）
--resume 跳過已有資料的股票（中斷後續跑）
"""
import argparse
import logging
import sys
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

log_dir = Path(__file__).parent.parent.parent / "logs"
log_dir.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_dir / "bsr_collect.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("bsr_collect")
_CST = timezone(timedelta(hours=8))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=None)
    parser.add_argument("--resume", action="store_true", help="跳過已有資料的股票")
    args = parser.parse_args()

    target_date = date.fromisoformat(args.date) if args.date else datetime.now(_CST).date()
    log.info("=== BSR 全量採集開始  date=%s  resume=%s ===", target_date, args.resume)

    from app.core.database import SessionLocal
    from sqlalchemy import text

    db = SessionLocal()
    try:
        rows = db.execute(text(
            "SELECT stock_id, name FROM stocks WHERE market='twse' AND is_active=1 ORDER BY stock_id"
        )).fetchall()
        stock_list = [(r[0], r[1] or "") for r in rows]
        log.info("共 %d 支上市股票", len(stock_list))

        done_ids: set[str] = set()
        if args.resume:
            done = db.execute(text(
                "SELECT DISTINCT stock_id FROM raw_broker_chips WHERE date=:d"
            ), {"d": str(target_date)}).fetchall()
            done_ids = {r[0] for r in done}
            log.info("已採集 %d 支，跳過", len(done_ids))
    finally:
        db.close()

    todo = [(sid, name) for sid, name in stock_list if sid not in done_ids]
    total = len(todo)
    est_min = total * 30 / 60
    log.info("待採集 %d 支（預估 %.0f 分鐘 / %.1f 小時）", total, est_min, est_min / 60)

    from app.collectors.bsr_broker_chips import BsrBrokerChipsCollector

    success = 0
    empty = 0
    errors = 0

    for i, (stock_id, name) in enumerate(todo, 1):
        db2 = SessionLocal()
        try:
            col = BsrBrokerChipsCollector(db2)
            count = col.collect_stocks(target_date, [stock_id])
            if count > 0:
                success += 1
                log.info("[%d/%d] %s %s -> %d brokers", i, total, stock_id, name, count)
            else:
                empty += 1
                log.debug("[%d/%d] %s %s -> no data", i, total, stock_id, name)
        except Exception as e:
            errors += 1
            log.warning("[%d/%d] %s %s ERROR: %s", i, total, stock_id, name, e)
        finally:
            db2.close()

        if i % 50 == 0:
            remain_min = (total - i) * 30 / 60
            log.info("=== 進度 %d/%d  success=%d empty=%d errors=%d  預估剩餘 %.0f 分鐘 ===",
                     i, total, success, empty, errors, remain_min)

    log.info("=== 完成  success=%d  empty=%d  errors=%d ===", success, empty, errors)


if __name__ == "__main__":
    main()
