# CHIP — 台灣籌碼情報平台

**Project Alpha**  ·  v0.6  ·  2026-06-28

三大法人、融資券、期貨未平倉的每日採集、衍生指標計算與視覺化分析平台。

---

## 架構

```
CHIP/
├── backend/            FastAPI + SQLite (port 8001)
│   ├── app/
│   │   ├── api/        REST API endpoints
│   │   ├── collectors/ 資料採集器（T86 / MI_MARGN / TAIFEX）
│   │   ├── models/     SQLAlchemy ORM models
│   │   ├── reporters/  Excel 日報產生器
│   │   ├── scheduler/  APScheduler 排程定義
│   │   └── main.py
│   ├── pyproject.toml
│   └── uv.lock
├── 啟動.bat            雙擊啟動後端（含 crash 自動重啟）
├── 結束.bat            雙擊停止後端 + 釋放 port 8001
├── launcher.ps1
├── stopper.ps1
└── README.md
```

## 整合方式（Phase A）

CHIP 後端獨立運行於 port **8001**，PYCHARTs 前端透過 Vite `/chip-api` proxy 存取。  
前端入口：http://localhost:5173（PYCHARTs 主專案啟動後點「籌碼分析」切換）

整合路線圖：
- **Phase A（目前）** — 獨立並行，proxy 轉送
- **Phase B** — CHIP API 移入 PYCHARTs FastAPI（port 8000）
- **Phase C** — chip.db 合併，統一資料層

---

## 安裝與啟動

**需求**
- Python 3.11+（由 uv 管理）
- [uv](https://github.com/astral-sh/uv) 套件管理器
- PYCHARTs 主專案（提供前端 Vite dev server）

**啟動步驟**
1. 確認 PYCHARTs 已啟動（Vite dev server 跑在 port 5173）
2. 雙擊 `啟動.bat` — 自動 `uv sync` + 啟動後端
3. 瀏覽器開啟 http://localhost:5173，點「籌碼分析」

**停止**
- 雙擊 `結束.bat`（只終止 port 8001，不影響主專案）

---

## API 端點

| Method | Path | 說明 |
|--------|------|------|
| GET | `/api/v1/chip/{stock_id}?days=N` | 個股籌碼時序 |
| GET | `/api/v1/chip/{stock_id}/summary` | 最新一日摘要 |
| GET | `/api/v1/futures?contract=TXF&days=N` | 期貨未平倉時序 |
| GET | `/api/v1/futures/latest` | 最新期貨快照 |
| GET | `/api/v1/stocks?q=query` | 股票搜尋 |
| GET | `/api/v1/options/expiries?contract=TXO` | 可用到期月份清單 |
| GET | `/api/v1/options/chain?contract=&expiry=` | 選擇權鏈（T字表原始資料） |
| GET | `/api/v1/options/support-resistance?contract=&expiry=` | 各履約價 OI（支撐壓力圖） |
| GET | `/api/v1/options/institutional` | 三大法人選擇權 Call/Put 分計 + 期/選合計 |
| GET | `/api/v1/options/large-traders?contract=TXO` | 大額交易人 Top5/Top10 未平倉 |
| GET | `/api/v1/options/put-call-ratio?days=22` | P/C 比趨勢（最近 N 天） |
| GET | `/api/v1/options/settlement` | 最後結算價（TAIFEX 代理） |
| POST | `/api/admin/collect/options` | 手動觸發選擇權採集 |
| GET | `/api/v1/reports` | 已生成的 Excel 日報清單 |
| GET | `/api/v1/reports/{date}` | 下載指定日期 Excel |
| POST | `/api/admin/backfill/chip` | 補抓歷史資料 |
| GET | `/api/admin/backfill/chip/status` | 補抓進度 |

Admin 端點需 Header：`X-Admin-Key: <key>`

---

## 排程

| 時間 (CST) | 工作 |
|------------|------|
| 09:00 | 股票清單刷新 |
| 16:35 | 三大法人 + 融資券 + 期貨OI 採集 |
| 17:00 | 分點進出採集 |
| 17:05 | 選擇權採集（TAIFEX OpenAPI chain/法人/大額/P/C比） |
| 17:15 | ChipProcessor 衍生指標計算 |
| 17:30 | Excel 日報生成 |
| 每月1日 08:00 | 交易日曆補充 |

---

## Changelog

### v0.6 — 2026-06-28
- 選擇權籌碼完整實作（P1~P3）：TAIFEX OpenAPI 全商品 13,259 筆鏈資料每日採集
- 新增 5 個 DB 表：raw_options_chain / institutional / inst_fo / large_traders / put_call_ratio
- REST API 7 個端點：chain / expiries / support-resistance / institutional / large-traders / put-call-ratio / settlement
- Scheduler 17:05 job_collect_options（每交易日自動採集）
- 前端「選擇權」新分頁（Toolbar 三頁切換）：支撐壓力橫條圖 / P/C 比趨勢 / 法人籌碼表 / 大額籌碼 / T字行情表 / 結算行情

### v0.5 — 2026-06-27
- TPEx 上櫃全股分點採集完成（909 支，191,634+ 筆，820 券商分點）
- MCP Chrome 真實瀏覽器架構繞過 Cloudflare Turnstile（Playwright 廢棄）
- 瀏覽器內記憶體佇列 + blob 下載架構（規避 Chrome PNA 封鎖）
- `load_tpex_json.py` 批次 upsert 工具
- `PrivateNetworkAccessMiddleware` 加入 backend（供未來 PNA 規格變更備用）

### v0.4 — 2026-06-26
- Phase 3：ChipReporter Excel 日報（5 sheets，512KB），17:30 自動生成
- Phase 4：PYCHARTs 前端整合（Toolbar 切換 + ECharts 三圖 + BackfillPanel）
- 啟動.bat / 結束.bat（不影響主專案）

### v0.2 — 2026-06-26
- Phase 2：ChipProcessor 衍生指標 + REST API

### v0.1 — 2026-06-26
- Phase 1：基礎採集架構（1,997 股，261 交易日，期貨 TXF+MXF）

---

> CONFIDENTIAL — Project Quant
