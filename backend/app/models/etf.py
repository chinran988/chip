"""CHIP-ETF 模組 — ETF 持股 models（ETF 交叉持股分析平台，對標 etfcross.com）。

形狀對齊既有 raw 表（見 raw.py 的 RawInstitutional / RawBrokerChips）：
ORM model + UniqueConstraint 複合唯一鍵 + BaseCollector.upsert()。
※ 新 model 檔必須註冊進 app/models/__init__.py 的 import，否則 create_all() 不建表。
"""
from sqlalchemy import (
    Column, String, Integer, BigInteger, Date, Float, DateTime, Boolean, UniqueConstraint,
)
from sqlalchemy.sql import func
from app.core.database import Base


class EtfInfo(Base):
    """ETF 主檔（追蹤標的，幾乎不變）。"""
    __tablename__ = "etf_info"

    etf_id = Column(String(10), primary_key=True)             # 0050 / 00981A
    name = Column(String(50), nullable=False)                 # 簡稱：元大台灣50
    full_name = Column(String(200))                           # 基金全名
    issuer = Column(String(20), nullable=False, index=True)   # 投信：元大/富邦/國泰/群益/統一/復華
    category = Column(String(40))                             # 國內成分股ETF / 國外成分股ETF(含連結式ETF)
    is_active = Column(Boolean, default=False)                # 主動式 True / 被動式 False
    is_domestic = Column(Boolean, default=True)               # 國內成分股(台股) True / 國外 False
    pcf_url = Column(String(300))                             # TWSE 路由表給的官方 PCF 落地頁
    data_endpoint = Column(String(300))                      # 實際採集端點（模板）
    engine = Column(String(12), default="http")              # http / headless / pending
    listing_date = Column(Date)
    updated_at = Column(DateTime, server_default=func.now())


class EtfHolding(Base):
    """ETF 每日成分股快照 — diff 引擎的地基。

    每列 = (資料日期 × 一檔 ETF × 一檔成分股)。UNIQUE(date, etf_id, stock_id)
    是 upsert 的 conflict 目標，缺它會讓 self.upsert() 對不上（CHIP 踩過的坑）。
    """
    __tablename__ = "etf_holdings"
    __table_args__ = (
        UniqueConstraint("date", "etf_id", "stock_id", name="uq_etf_holding"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False, index=True)           # PCF 標示的資料/交易日期（非採集日）
    etf_id = Column(String(10), nullable=False, index=True)
    stock_id = Column(String(20), nullable=False, index=True) # 成分股代號（外股可能非數字）
    stock_name = Column(String(100))
    shares = Column(BigInteger, default=0)                    # 股數
    weight = Column(Float)                                    # 權重 %（投信有給就存，否則留空由股價回算）
    market_value = Column(BigInteger)                         # 市值/金額（投信有給就存，可空）
    collected_at = Column(DateTime, server_default=func.now())
