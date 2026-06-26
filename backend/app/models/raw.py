from sqlalchemy import Column, String, Integer, BigInteger, Date, Float, DateTime, UniqueConstraint
from sqlalchemy.sql import func
from app.core.database import Base


class RawInstitutional(Base):
    """三大法人買賣超（TWSE T86）"""
    __tablename__ = "raw_institutional"
    __table_args__ = (UniqueConstraint("date", "stock_id", name="uq_inst_date_stock"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False, index=True)
    stock_id = Column(String(10), nullable=False, index=True)
    foreign_buy = Column(BigInteger, default=0)
    foreign_sell = Column(BigInteger, default=0)
    trust_buy = Column(BigInteger, default=0)
    trust_sell = Column(BigInteger, default=0)
    dealer_buy = Column(BigInteger, default=0)       # 自營商自行
    dealer_sell = Column(BigInteger, default=0)
    dealer_hedge_buy = Column(BigInteger, default=0)  # 自營商避險
    dealer_hedge_sell = Column(BigInteger, default=0)
    created_at = Column(DateTime, server_default=func.now())


class RawBrokerChips(Base):
    """券商分點進出（TWSE TWT38U，per-stock query）"""
    __tablename__ = "raw_broker_chips"
    __table_args__ = (UniqueConstraint("date", "stock_id", "branch_id", name="uq_broker_date_stock_branch"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False, index=True)
    stock_id = Column(String(10), nullable=False, index=True)
    branch_id = Column(String(10), nullable=False, index=True)
    branch_name = Column(String(100))
    buy_volume = Column(BigInteger, default=0)   # 張
    sell_volume = Column(BigInteger, default=0)
    buy_value = Column(BigInteger, default=0)    # 千元
    sell_value = Column(BigInteger, default=0)
    created_at = Column(DateTime, server_default=func.now())


class RawMargin(Base):
    """融資融券餘額（TWSE MI_MARGN）"""
    __tablename__ = "raw_margin"
    __table_args__ = (UniqueConstraint("date", "stock_id", name="uq_margin_date_stock"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False, index=True)
    stock_id = Column(String(10), nullable=False, index=True)
    margin_buy = Column(BigInteger, default=0)      # 融資買進
    margin_sell = Column(BigInteger, default=0)     # 融資賣出
    margin_balance = Column(BigInteger, default=0)  # 融資餘額
    margin_limit = Column(BigInteger, default=0)    # 融資限額
    short_sell = Column(BigInteger, default=0)      # 融券賣出
    short_buy = Column(BigInteger, default=0)       # 融券買進
    short_balance = Column(BigInteger, default=0)   # 融券餘額
    short_limit = Column(BigInteger, default=0)     # 融券限額
    created_at = Column(DateTime, server_default=func.now())


class RawFuturesOI(Base):
    """期貨三大法人未平倉（TAIFEX）"""
    __tablename__ = "raw_futures_oi"
    __table_args__ = (UniqueConstraint("date", "contract", "expiry", name="uq_fut_date_contract"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False, index=True)
    contract = Column(String(20), nullable=False, index=True)  # TXF / MXF / etc.
    expiry = Column(String(10), default="all")                 # 近月 / 所有序列
    foreign_long = Column(BigInteger, default=0)
    foreign_short = Column(BigInteger, default=0)
    trust_long = Column(BigInteger, default=0)
    trust_short = Column(BigInteger, default=0)
    dealer_long = Column(BigInteger, default=0)
    dealer_short = Column(BigInteger, default=0)
    oi_total = Column(BigInteger, default=0)
    created_at = Column(DateTime, server_default=func.now())


class RawOptionsOI(Base):
    """選擇權各履約價未平倉"""
    __tablename__ = "raw_options_oi"
    __table_args__ = (UniqueConstraint("date", "contract", "expiry", "strike", "option_type", name="uq_opt_date_strike"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False, index=True)
    contract = Column(String(20), nullable=False)
    expiry = Column(String(10))
    strike = Column(Integer, nullable=False)
    option_type = Column(String(4), nullable=False)  # call / put
    oi = Column(BigInteger, default=0)
    volume = Column(BigInteger, default=0)
    created_at = Column(DateTime, server_default=func.now())


class RawMajorHolders(Base):
    """千張大戶持股比例（TDCC，每週五）"""
    __tablename__ = "raw_major_holders"
    __table_args__ = (UniqueConstraint("date", "stock_id", name="uq_holders_date_stock"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False, index=True)
    stock_id = Column(String(10), nullable=False, index=True)
    holders_1k_plus_pct = Column(Float)   # 1000張以上持股比例
    holders_400_1k_pct = Column(Float)    # 400~999張
    holders_200_400_pct = Column(Float)   # 200~399張
    holders_count = Column(Integer)        # 1000張以上人數
    total_holders = Column(Integer)        # 總股東人數
    created_at = Column(DateTime, server_default=func.now())
