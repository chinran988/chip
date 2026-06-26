"""Phase 1 verification script — run with: uv run python verify_phase1.py"""
import logging, sys
from datetime import date
from sqlalchemy import text

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s", stream=sys.stdout)

from app.core.database import init_db, SessionLocal
init_db()
db = SessionLocal()

# ── 1. 三大法人 今日 ─────────────────────────────────────
from app.collectors.twse_institutional import InstitutionalCollector
today = date(2026, 6, 26)
n = InstitutionalCollector(db).collect(today)
print(f"\n[1] Institutional {today}: {n} rows saved")

# ── 2. 查 DB Top 5 外資 ──────────────────────────────────
sql = text("""
    SELECT stock_id,
           foreign_buy - foreign_sell AS f_net,
           trust_buy   - trust_sell   AS t_net
    FROM   raw_institutional
    WHERE  date = :d
    ORDER  BY ABS(foreign_buy - foreign_sell) DESC
    LIMIT  5
""")
rows = db.execute(sql, {"d": str(today)}).fetchall()
print("\nTop 5 by foreign net:")
for r in rows:
    print(f"  {r[0]}: 外資淨={r[1]:>10,}  投信淨={r[2]:>10,}")

# ── 3. 融資融券 (試多個日期) ─────────────────────────────
from app.collectors.twse_margin import MarginCollector
print()
for d in [date(2026, 6, 26), date(2026, 6, 25), date(2026, 6, 24)]:
    try:
        nm = MarginCollector(db).collect(d)
        print(f"[2] Margin {d}: {nm} rows")
        if nm > 0:
            break
    except Exception as e:
        print(f"[2] Margin {d}: error — {e}")

# ── 4. 股票清單確認 ──────────────────────────────────────
cnt = db.execute(text("SELECT COUNT(*) FROM stocks")).scalar()
twse = db.execute(text("SELECT COUNT(*) FROM stocks WHERE market='twse'")).scalar()
otc  = db.execute(text("SELECT COUNT(*) FROM stocks WHERE market='otc'")).scalar()
print(f"\n[3] Stocks in DB: total={cnt}  TWSE={twse}  OTC={otc}")

# ── 5. 交易日曆確認 ──────────────────────────────────────
trading = db.execute(text("SELECT COUNT(*) FROM trading_calendar WHERE is_trading_day=1 AND date LIKE '2026%'")).scalar()
print(f"[4] Trading days 2026: {trading}")

db.close()
print("\n=== Phase 1 verification DONE ===")
