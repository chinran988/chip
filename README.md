# CHIP — 台灣籌碼情報平台

**Project Alpha**  ·  v0.4  ·  2026-06-26

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
| 17:15 | ChipProcessor 衍生指標計算 |
| 17:30 | Excel 日報生成 |
| 每月1日 08:00 | 交易日曆補充 |

---

## Changelog

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
