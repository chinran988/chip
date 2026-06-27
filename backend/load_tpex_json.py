"""讀取瀏覽器下載的 tpex_batch_*.json，upsert 到 raw_broker_chips。

用法：
    python load_tpex_json.py                  # 掃 Downloads 全部 tpex_batch_*.json
    python load_tpex_json.py path/to/file.json
"""
import sys, json, glob
from datetime import date
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).parent))

from app.core.database import SessionLocal
from app.models.raw import RawBrokerChips
from app.collectors.bsr_broker_chips import BsrBrokerChipsCollector
from sqlalchemy import text

DOWNLOADS = Path.home() / "Downloads"


def _load_file(path: Path) -> int:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    rows = [{
        "date":        date.fromisoformat(r["date"]),
        "stock_id":    r["code"],
        "branch_id":   r["bid"],
        "branch_name": r["bn"],
        "buy_volume":  r["bvol"],
        "sell_volume": r["svol"],
        "buy_value":   r["bval"],
        "sell_value":  r["sval"],
    } for r in raw]
    if not rows:
        return 0
    db = SessionLocal()
    try:
        col = BsrBrokerChipsCollector(db)
        col.upsert(RawBrokerChips, rows, ["date", "stock_id", "branch_id"])
        db.commit()
        return len(rows)
    finally:
        db.close()


def main():
    if len(sys.argv) > 1:
        files = [Path(sys.argv[1])]
    else:
        files = sorted(DOWNLOADS.glob("tpex_batch_*.json"))
        if not files:
            print("Downloads 內無 tpex_batch_*.json")
            return

    total = 0
    for f in files:
        n = _load_file(f)
        print(f"  {f.name}: {n} 筆")
        total += n

    db = SessionLocal()
    try:
        cnt = db.execute(text(
            "SELECT COUNT(*) FROM raw_broker_chips WHERE date >= '2026-06-27'"
        )).scalar()
        print(f"\n合計寫入: {total} 筆 | DB 中 >=2026-06-27 共 {cnt} 筆")
    finally:
        db.close()


if __name__ == "__main__":
    main()
