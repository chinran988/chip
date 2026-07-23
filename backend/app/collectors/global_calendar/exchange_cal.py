"""期貨/衍生品交易所官方行事曆 —— 來源：exchange_calendars（金融業標準函式庫，規則制）。

補 investing 假期資料的缺口：investing 只收「證券」交易所，且不給早收時間。
exchange_calendars 內建 50+ 交易所的官方交易行事曆（規則制→涵蓋多年），含假日與**早收**，
本模組取目標期貨/衍生品所，早收時間換算為台灣時間，來源標記 source='exchange_calendars'。

★資料範圍：函式庫各行事曆有其收錄上限（多數到 2026，2027 未收）→ 本模組自動夾在
  [max(2018, first_session), min(2026, last_session)]，不越界（越界會把整年誤判成假日）。
"""
import datetime

import pandas as pd

# code = exchange_calendars 代碼；exchange = 顯示名；country/region 與 investing 資料一致以利分區
EXCHANGES = [
    {"code": "XEUR", "exchange": "EUREX",        "country": "Germany",   "region": "歐洲"},
    {"code": "XHKG", "exchange": "HKEX 期貨",     "country": "Hong Kong", "region": "亞太"},
    {"code": "XTKS", "exchange": "JPX/OSE 期貨",  "country": "Japan",     "region": "亞太"},
    {"code": "XSES", "exchange": "SGX 期貨",      "country": "Singapore", "region": "亞太"},
    {"code": "XTAI", "exchange": "TAIFEX 台指期", "country": "Taiwan",    "region": "亞太"},
]
LO, HI = "2018-01-01", "2026-12-31"
TW = "Asia/Taipei"


def _range(cal):
    lo = max(pd.Timestamp(LO), pd.Timestamp(cal.first_session).tz_localize(None))
    hi = min(pd.Timestamp(HI), pd.Timestamp(cal.last_session).tz_localize(None))
    return lo, hi


def _named_holidays(cal, lo, hi):
    """回傳 {date(iso): 假日名}。regular_holidays 有名；adhoc（一次性，如颱風）無名。"""
    out = {}
    try:
        s = cal.regular_holidays.holidays(lo, hi, return_name=True)
        for ts, name in s.items():
            out[pd.Timestamp(ts).date().isoformat()] = str(name)
    except Exception:
        pass
    return out


def _early_closes(sched, tz):
    """早收偵測：當地收盤時刻**早於「當年」眾數**才算。
    用「當年」而非全期 → 避開交易所規則性調整交易時段（如 JPX 2024/11 收盤 15:00→15:30）被誤判；
    用「更早」而非「不同」→ 延長交易時段(變晚)不會被當早收。回傳 [(iso, tw_str, local_hhmm, year_norm)]。
    """
    if sched.empty:
        return []
    loc = sched["close"].dt.tz_convert(tz)
    hhmm = loc.dt.strftime("%H:%M")
    yr = pd.DatetimeIndex(sched.index).year
    ynorm = {}
    for y in sorted(set(yr)):
        m = hhmm[yr == y].mode()
        ynorm[y] = m.iloc[0] if len(m) else None
    out = []
    for idx, row in sched.iterrows():
        y = pd.Timestamp(idx).year
        nm = ynorm.get(y)
        loc_c = pd.Timestamp(row["close"]).tz_convert(tz)
        s = loc_c.strftime("%H:%M")
        if nm and s < nm:   # 等寬 HH:MM 字串比較即時間比較
            tw = pd.Timestamp(row["close"]).tz_convert(TW)
            out.append((pd.Timestamp(idx).date().isoformat(),
                        f"{tw.strftime('%m/%d %H:%M')}（台灣）", s, nm))
    return out


def preview(codes=None):
    """算出要入庫的記錄（不寫 DB），供檢視。回傳 (records, summary)。"""
    import exchange_calendars as xcals
    codes = codes or [e["code"] for e in EXCHANGES]
    cfg = {e["code"]: e for e in EXCHANGES}
    records, summary = [], []
    for code in codes:
        e = cfg[code]
        cal = xcals.get_calendar(code)
        lo, hi = _range(cal)
        sched = cal.schedule.loc[lo:hi]
        sess_dates = {pd.Timestamp(x).date() for x in sched.index}
        named = _named_holidays(cal, lo, hi)
        # 假日 = 區間內工作日但非交易日
        n_hol = n_early = 0
        for d in pd.bdate_range(lo, hi):
            if d.date() not in sess_dates:
                iso = d.date().isoformat()
                records.append({
                    "date": iso, "country": e["country"], "exchange": e["exchange"],
                    "region": e["region"], "name": named.get(iso, "休市（交易所公告）"),
                    "type": "休市", "close_time": None, "open_time": None,
                    "note": None, "source": "exchange_calendars",
                })
                n_hol += 1
        # 早收（當年眾數＋只算更早，避開規則性交易時段調整）
        for iso, tw_str, loc_hhmm, nm in _early_closes(sched, cal.tz):
            records.append({
                "date": iso, "country": e["country"], "exchange": e["exchange"],
                "region": e["region"], "name": named.get(iso, "早收"),
                "type": "早收", "close_time": tw_str, "open_time": None,
                "note": f"當地 {loc_hhmm} 收盤（常規 {nm}）", "source": "exchange_calendars",
            })
            n_early += 1
        summary.append({"code": code, "exchange": e["exchange"],
                        "range": f"{lo.date()}~{hi.date()}", "holidays": n_hol, "early": n_early})
    return records, summary


def collect(codes=None):
    from .db import conn, upsert_holidays, log
    records, summary = preview(codes)
    c = conn()
    n = upsert_holidays(c, records, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    log(c, "exchange-cal", True, n, "; ".join(f"{s['exchange']}:{s['holidays']}+{s['early']}" for s in summary))
    c.commit()
    c.close()
    return {"records": n, "summary": summary}


def cross_check_cme():
    """CME：函式庫 vs 手動 Google Sheet（source='sheet'）2026 對比，回報差異（不入庫）。"""
    import exchange_calendars as xcals
    from .db import conn
    cal = xcals.get_calendar("CMES")
    lo, hi = pd.Timestamp("2026-01-01"), pd.Timestamp("2026-12-31")
    sched = cal.schedule.loc[lo:hi]
    sess_dates = {pd.Timestamp(x).date() for x in sched.index}
    named = _named_holidays(cal, lo, hi)
    lib_full = {d.date().isoformat(): named.get(d.date().isoformat(), "休市")
                for d in pd.bdate_range(lo, hi) if d.date() not in sess_dates}
    lib_early = {iso: f"{tw_str} 當地{loc_hhmm}" for iso, tw_str, loc_hhmm, nm in _early_closes(sched, cal.tz)}
    norm = _early_closes(sched, cal.tz) and None  # 每年眾數，此處不回單一值
    c = conn()
    sheet = {r["date"]: (r["type"], r["close_time"]) for r in
             c.execute("SELECT date,type,close_time FROM holidays WHERE exchange='CME' AND source='sheet'")}
    c.close()
    return {"lib_full": lib_full, "lib_early": lib_early, "sheet": sheet, "lib_norm_close": norm}
