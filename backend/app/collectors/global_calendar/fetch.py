"""investing.com 抓取層。

實測（2026-07-20）：純 requests/curl 直連 investing.com → HTTP 403（邊緣以 TLS/指紋擋）；
curl_cffi 以 Chrome 指紋模擬 → HTTP 200。故爬蟲基礎採 curl_cffi。
"""
import random
import time

from curl_cffi import requests as cffi

IMPERSONATE = "chrome"
BASE_HEADERS = {
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.investing.com/",
    "X-Requested-With": "XMLHttpRequest",
}

# 分階段爬取節流（使用者指定 2026-07-20）：每階段間隔 60 秒、隨機 ±15 秒。
STAGE_BASE_SEC = 60
STAGE_JITTER_SEC = 15


def fetch(url, method="GET", data=None, headers=None, timeout=30):
    """回傳 response text；非 2xx 會 raise。"""
    h = dict(BASE_HEADERS)
    if headers:
        h.update(headers)
    fn = cffi.post if method.upper() == "POST" else cffi.get
    kwargs = dict(impersonate=IMPERSONATE, timeout=timeout, headers=h)
    if data is not None:
        kwargs["data"] = data
    resp = fn(url, **kwargs)
    resp.raise_for_status()
    return resp.text


def stage_sleep(verbose=True):
    """兩個爬取階段之間的禮貌等待：60 ± 15 秒。回傳實際秒數。"""
    secs = STAGE_BASE_SEC + random.uniform(-STAGE_JITTER_SEC, STAGE_JITTER_SEC)
    if verbose:
        print(f"[pace] 等待 {secs:.0f}s 再進行下一階段…", flush=True)
    time.sleep(secs)
    return secs
