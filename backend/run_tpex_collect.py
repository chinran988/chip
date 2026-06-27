"""TPEx 上櫃券商分點進出 — Playwright 自動化採集（Cloudflare Turnstile 自動通過）

用法：
    python run_tpex_collect.py [--date YYYY-MM-DD] [--resume] [--headless]

流程：
  1. 啟動有頭 Chromium → 開啟 brokerBS.html → Turnstile 自動通過
  2. 每支上櫃股票：取 token → fetch CSV → 解析 → 存 DB
  3. Turnstile reset → 等 30±10 秒 → 下一支
"""
import argparse
import csv
import io
import logging
import random
import sys
import time
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
        logging.FileHandler(log_dir / "tpex_collect.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("tpex_collect")
_CST = timezone(timedelta(hours=8))

_TPEX_URL = "https://www.tpex.org.tw/zh-tw/mainboard/trading/info/brokerBS.html"
_DELAY_BASE  = 30.0
_DELAY_JITTER = 10.0   # ±10 秒


# ── CSV 解析 ────────────────────────────────────────────────────────────────

def _clean_int(s: str) -> int:
    try:
        return int(str(s).replace(",", "").strip() or "0")
    except ValueError:
        return 0


def _parse_csv(csv_text: str, target_date: date, stock_id: str) -> list[dict]:
    """解析 TPEx brokerBS CSV。

    格式：
      行0: 券商買賣證券成交價量資訊
      行1: 證券代碼,XXXX
      行2: 序號,券商,價格,買進股數,賣出股數  (header)
      行3+: "1","1020 合庫","2310","0","1000"

    券商欄格式：4 位 branch_id + 空格 + 券商名稱
    單位：股(÷1000=張)，元(×shares÷1000=千元)
    """
    lines = csv_text.splitlines()

    # 找 header 行
    data_start = 0
    for i, line in enumerate(lines):
        stripped = line.strip().strip('"')
        if stripped.startswith("序號"):
            data_start = i + 1
            break
    if data_start == 0:
        return []

    agg: dict[str, dict] = {}
    reader = csv.reader(lines[data_start:])
    for parts in reader:
        if len(parts) < 5:
            continue
        broker_raw = parts[1].strip()
        if not broker_raw:
            continue

        # "1020 合庫" → id="1020", name="合庫"
        sp = broker_raw.split(" ", 1)
        branch_id   = sp[0].strip()
        branch_name = sp[1].strip() if len(sp) > 1 else broker_raw

        if not branch_id:
            continue

        try:
            price    = float(parts[2].replace(",", "").strip() or "0")
            buy_sh   = _clean_int(parts[3])
            sell_sh  = _clean_int(parts[4])
        except (ValueError, IndexError):
            continue

        if branch_id not in agg:
            agg[branch_id] = {"name": branch_name, "buy": 0.0, "sell": 0.0,
                               "bval": 0.0, "sval": 0.0}
        rec = agg[branch_id]
        if branch_name:
            rec["name"] = branch_name
        rec["buy"]  += buy_sh
        rec["sell"] += sell_sh
        rec["bval"] += buy_sh  * price
        rec["sval"] += sell_sh * price

    result = []
    for bid, rec in agg.items():
        result.append({
            "date":        target_date,
            "stock_id":    stock_id,
            "branch_id":   bid,
            "branch_name": rec["name"],
            "buy_volume":  int(rec["buy"])  // 1000,   # 股 → 張
            "sell_volume": int(rec["sell"]) // 1000,
            "buy_value":   int(rec["bval"]) // 1000,   # 元 → 千元
            "sell_value":  int(rec["sval"]) // 1000,
        })
    return result


# ── Playwright 輔助 ─────────────────────────────────────────────────────────

def _wait_for_token(page, timeout_s: float = 60) -> bool:
    """等待 Turnstile token 出現（非空）。"""
    start = time.time()
    while time.time() - start < timeout_s:
        try:
            token = page.evaluate(
                "document.querySelector('input[name=\"cf-turnstile-response\"]')?.value || ''"
            )
            if token and len(token) > 20:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def _fetch_csv(page, stock_id: str) -> str:
    """在頁面 context 中帶 token fetch CSV（同源，無 CORS）。"""
    try:
        result = page.evaluate(f"""
        (async () => {{
            const token = document.querySelector('input[name="cf-turnstile-response"]').value;
            if (!token || token.length < 20) return '';
            const url = `/www/zh-tw/afterTrading/brokerBS?code={stock_id}&cf-turnstile-response=${{encodeURIComponent(token)}}&response=utf-8`;
            const resp = await fetch(url, {{ credentials: 'include' }});
            return await resp.text();
        }})()
        """)
        return result or ""
    except Exception as e:
        log.debug("fetch_csv error: %s", e)
        return ""


def _reset_turnstile(page) -> None:
    try:
        page.evaluate("if(typeof turnstile !== 'undefined') turnstile.reset('#myWidget')")
    except Exception:
        pass


# ── 主流程 ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date",     default=None,         help="採集日期 YYYY-MM-DD（預設今日）")
    parser.add_argument("--resume",   action="store_true",  help="跳過已有資料的股票")
    parser.add_argument("--headless", action="store_true",  help="無頭模式（可能被 Cloudflare 封鎖）")
    args = parser.parse_args()

    target_date = date.fromisoformat(args.date) if args.date else datetime.now(_CST).date()
    log.info("=== TPEx 上櫃分點採集開始  date=%s  resume=%s  headless=%s ===",
             target_date, args.resume, args.headless)

    from app.core.database import SessionLocal
    from app.models.raw import RawBrokerChips
    from sqlalchemy import text

    # 取上櫃股票清單
    db = SessionLocal()
    try:
        rows = db.execute(text(
            "SELECT stock_id, name FROM stocks WHERE market='otc' AND is_active=1 ORDER BY stock_id"
        )).fetchall()
        stock_list = [(r[0], r[1] or "") for r in rows]
        log.info("共 %d 支上櫃股票", len(stock_list))

        done_ids: set[str] = set()
        if args.resume:
            done = db.execute(text(
                "SELECT DISTINCT stock_id FROM raw_broker_chips WHERE date=:d"
                " AND stock_id IN (SELECT stock_id FROM stocks WHERE market='otc')"
            ), {"d": str(target_date)}).fetchall()
            done_ids = {r[0] for r in done}
            log.info("已採集 %d 支，跳過", len(done_ids))
    finally:
        db.close()

    todo = [(sid, name) for sid, name in stock_list if sid not in done_ids]
    total = len(todo)
    est_min = total * _DELAY_BASE / 60
    log.info("待採集 %d 支（預估 %.0f 分 / %.1f 小時）", total, est_min, est_min / 60)

    from playwright.sync_api import sync_playwright

    success = 0
    empty   = 0
    errors  = 0

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=args.headless,
            executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx  = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/148.0.0.0 Safari/537.36",
        )
        page = ctx.new_page()

        log.info("開啟 TPEx 頁面，等待 Cloudflare Turnstile 通過…")
        page.goto(_TPEX_URL, wait_until="domcontentloaded", timeout=60_000)

        if not _wait_for_token(page, timeout_s=90):
            log.error("Cloudflare Turnstile 90 秒內未通過，中止")
            browser.close()
            return

        log.info("Turnstile 通過，開始採集")

        for i, (stock_id, name) in enumerate(todo, 1):
            # 確保 token 有效
            if not _wait_for_token(page, timeout_s=45):
                log.warning("[%d/%d] %s 等待 token 逾時，強制 reset", i, total, stock_id)
                _reset_turnstile(page)
                if not _wait_for_token(page, timeout_s=30):
                    log.warning("[%d/%d] %s 仍無 token，跳過", i, total, stock_id)
                    errors += 1
                    continue

            try:
                csv_text = _fetch_csv(page, stock_id)

                if not csv_text or len(csv_text) < 30:
                    empty += 1
                    log.debug("[%d/%d] %s %s -> 無資料", i, total, stock_id, name)
                else:
                    parsed = _parse_csv(csv_text, target_date, stock_id)
                    if parsed:
                        db2 = SessionLocal()
                        try:
                            from app.collectors.bsr_broker_chips import BsrBrokerChipsCollector
                            col = BsrBrokerChipsCollector(db2)
                            col.upsert(RawBrokerChips, parsed, ["date", "stock_id", "branch_id"])
                            db2.commit()
                            success += 1
                            log.info("[%d/%d] %s %s -> %d brokers", i, total, stock_id, name, len(parsed))
                        finally:
                            db2.close()
                    else:
                        empty += 1
                        log.debug("[%d/%d] %s %s -> 解析 0 筆", i, total, stock_id, name)

            except Exception as e:
                errors += 1
                log.warning("[%d/%d] %s %s ERROR: %s", i, total, stock_id, name, e)

            # 進度報告
            if i % 50 == 0:
                remain_min = (total - i) * _DELAY_BASE / 60
                log.info("=== 進度 %d/%d  success=%d empty=%d errors=%d  剩餘預估 %.0f 分 ===",
                         i, total, success, empty, errors, remain_min)

            if i < total:
                # Reset Turnstile，準備下一支
                _reset_turnstile(page)
                delay = _DELAY_BASE + random.uniform(-_DELAY_JITTER, _DELAY_JITTER)
                log.debug("等待 %.1f 秒…", delay)
                time.sleep(delay)

        browser.close()

    log.info("=== 完成  success=%d  empty=%d  errors=%d ===", success, empty, errors)


if __name__ == "__main__":
    main()
