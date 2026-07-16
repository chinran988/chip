"""CHIP 每日採集腳本
用法：
  python collect_daily.py [YYYY-MM-DD] [--bsr|--no-bsr]
  --bsr      只跑 BSR（19:30 排程用）
  --no-bsr   跑 daily + TWT38U，不跑 BSR（20:33 排程用）
  不給 flag  全跑（手動補採用）
"""
import sys, os, subprocess, json, time, random, datetime, sqlite3
import requests as _req

# ── 解析 mode ─────────────────────────────────────────────────────────────
_args = sys.argv[1:]
MODE_BSR_ONLY = "--bsr"    in _args
MODE_NO_BSR   = "--no-bsr" in _args
_date_args = [a for a in _args if not a.startswith("--")]

CHIP_DIR = r"C:\Users\Inspiration\Documents\Project Quant\CHIP"
BACKEND  = os.path.join(CHIP_DIR, "backend")
PYTHON   = os.path.join(BACKEND, ".venv", "Scripts", "python.exe")
WORKER   = os.path.join(os.environ.get("TEMP", r"C:\Users\INSPIR~1\AppData\Local\Temp"), "bsr_worker.py")
LOG      = os.path.join(os.environ.get("TEMP", r"C:\Users\INSPIR~1\AppData\Local\Temp"), "chip_daily.log")
DB       = os.path.join(CHIP_DIR, "data", "chip.db")

API      = "http://localhost:8001"
API_KEY  = "change-me-to-a-long-random-string"
HEADERS  = {"X-API-Key": API_KEY}

BSR_WORKER_TIMEOUT = 90
BSR_DELAY_BASE     = 15.0
BSR_DELAY_JITTER   = 5.0
BSR_SESSION_RESET  = 20

TARGET = datetime.date.fromisoformat(_date_args[0]) if _date_args else datetime.date.today()

def log(msg):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")

# ── Step 1: daily（法人 + 期貨OI）──────────────────────────────────────────
def step_daily():
    log("=== Step 1: daily 採集（法人/期貨OI）===")
    try:
        r = _req.post(f"{API}/api/admin/collect/daily", headers=HEADERS, timeout=300)
        d = r.json()
        log(f"  institutional={d['results'].get('twse_institutional',0)}  futures={d['results'].get('taifex_futures',0)}")
    except Exception as e:
        log(f"  daily 失敗: {e}")

# ── Step 2: TWT38U 全量分點 ───────────────────────────────────────────────
def _get_twse_stocks():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT stock_id FROM stocks WHERE market='twse' AND is_active=1 ORDER BY stock_id")
    ids = [r[0] for r in c.fetchall()]
    conn.close()
    return ids

def _get_twse_done(date_str):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute(f"SELECT DISTINCT stock_id FROM raw_broker_chips WHERE date='{date_str}' AND source!='bsr'", )
    done = {r[0] for r in c.fetchall()}
    conn.close()
    return done

def step_twt38u():
    log(f"=== Step 2: TWT38U 分點採集（{TARGET}）===")
    sys.path.insert(0, BACKEND)
    os.chdir(BACKEND)
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BACKEND, ".env"))
    from app.core.database import SessionLocal
    from app.collectors.twse_broker_chips import BrokerChipsCollector
    from app.models.raw import RawBrokerChips

    stocks = _get_twse_stocks()
    log(f"  全量 {len(stocks)} 支")

    db = SessionLocal()
    try:
        col = BrokerChipsCollector(db)
        total = col.collect_stocks(TARGET, stocks)
        db.commit()
        log(f"  TWT38U 完成: {total} 筆")
    except Exception as e:
        log(f"  TWT38U 錯誤: {e}")
    finally:
        db.close()

# ── Step 3: BSR 全量分點（子進程 v4）────────────────────────────────────────
def _get_bsr_pending(date_str):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute(f"""
        SELECT s.stock_id FROM stocks s
        WHERE s.market='twse' AND s.is_active=1
          AND s.stock_id NOT IN (
            SELECT DISTINCT stock_id FROM raw_broker_chips WHERE date='{date_str}'
          )
        ORDER BY s.stock_id
    """)
    ids = [r[0] for r in c.fetchall()]
    conn.close()
    return ids

RESULT_FILE = os.path.join(os.environ.get("TEMP", r"C:\Users\INSPIR~1\AppData\Local\Temp"), "bsr_result.json")

def _fetch_bsr_one(stock_id, date_str):
    if os.path.exists(RESULT_FILE):
        os.remove(RESULT_FILE)
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.Popen(
        [PYTHON, WORKER, stock_id, date_str, RESULT_FILE],
        cwd=BACKEND, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        proc.wait(timeout=BSR_WORKER_TIMEOUT)
    except subprocess.TimeoutExpired:
        proc.kill(); proc.wait()
        return {"ok": False, "error": "timeout", "rows": 0}
    if os.path.exists(RESULT_FILE):
        with open(RESULT_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"ok": False, "error": "no result", "rows": 0}

def step_bsr():
    date_str = TARGET.isoformat()
    log(f"=== Step 3: BSR 分點採集（{date_str}）===")
    pending = _get_bsr_pending(date_str)
    log(f"  待採集: {len(pending)} 支")

    done = fail = timeout_cnt = 0
    for i, stock_id in enumerate(pending):
        res = _fetch_bsr_one(stock_id, date_str)
        rows = res.get("rows", 0)
        if not res["ok"]:
            if "timeout" in res.get("error", ""):
                timeout_cnt += 1
            else:
                fail += 1
        elif rows > 0:
            done += 1

        if i % 10 == 0 or i < 5:
            log(f"  BSR {i+1}/{len(pending)}  done={done} fail={fail} to={timeout_cnt}  {stock_id} {'✓' if rows else '—'}")

        time.sleep(BSR_DELAY_BASE + random.uniform(-BSR_DELAY_JITTER, BSR_DELAY_JITTER))

    log(f"  BSR 結束: done={done} fail={fail} timeout={timeout_cnt}")

# ── 主流程 ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    log(f"======= CHIP 每日採集開始 {TARGET}  mode={'BSR-only' if MODE_BSR_ONLY else 'no-BSR' if MODE_NO_BSR else 'ALL'} =======")
    # 註：TWT38U 已停用（2026-07-13）。原為 Phase 1 上市分點來源，但被 BSR 完全取代——
    # BSR 涵蓋相同上市分點且多含成交均價、可補前一交易日；TWT38U 僅當日、無均價且已失效。
    # 保留 step_twt38u() 函式定義但不再呼叫。若要重啟，取消下方註解即可。
    if MODE_BSR_ONLY:
        step_bsr()
    elif MODE_NO_BSR:
        step_daily()
        # step_twt38u()   # 停用：BSR 已覆蓋上市分點
    else:
        step_daily()
        # step_twt38u()   # 停用：BSR 已覆蓋上市分點
        step_bsr()
    log(f"======= CHIP 每日採集結束 {TARGET} =======")
