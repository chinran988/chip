from sqlalchemy import Column, String, Integer, BigInteger, Date, Float, DateTime, UniqueConstraint
from sqlalchemy.sql import func
from app.core.database import Base

# ── 選擇權相關 models ─────────────────────────────────────────────────────────

class RawOptionsChain(Base):
    """選擇權每日行情（TAIFEX OpenAPI /DailyMarketReportOpt，所有商品）"""
    __tablename__ = "raw_options_chain"
    __table_args__ = (
        UniqueConstraint("date", "contract", "expiry", "strike", "call_put", "trading_session", name="uq_opt_chain"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False, index=True)
    contract = Column(String(20), nullable=False, index=True)
    expiry = Column(String(20), nullable=False)
    strike = Column(Integer, nullable=False)
    call_put = Column(String(4), nullable=False)
    trading_session = Column(String(10), nullable=False, default="一般")  # 一般（日盤）/ 盤後（夜盤）
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(BigInteger, default=0)
    settlement_price = Column(Float)
    open_interest = Column(BigInteger, default=0)
    best_bid = Column(Float)
    best_ask = Column(Float)
    created_at = Column(DateTime, server_default=func.now())


class RawOptionsInstitutional(Base):
    """三大法人選擇權 Call/Put 分計（TAIFEX OpenAPI）"""
    __tablename__ = "raw_options_institutional"
    __table_args__ = (UniqueConstraint("date", "contract_code", "call_put", "institution", name="uq_opt_inst"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False, index=True)
    contract_code = Column(String(50), nullable=False)
    call_put = Column(String(6), nullable=False)
    institution = Column(String(10), nullable=False)
    buy_vol = Column(BigInteger, default=0)
    buy_val = Column(BigInteger, default=0)
    sell_vol = Column(BigInteger, default=0)
    sell_val = Column(BigInteger, default=0)
    net_vol = Column(BigInteger, default=0)
    net_val = Column(BigInteger, default=0)
    oi_long = Column(BigInteger, default=0)
    oi_long_val = Column(BigInteger, default=0)
    oi_short = Column(BigInteger, default=0)
    oi_short_val = Column(BigInteger, default=0)
    oi_net = Column(BigInteger, default=0)
    oi_net_val = Column(BigInteger, default=0)
    created_at = Column(DateTime, server_default=func.now())


class RawOptionsInstFO(Base):
    """三大法人期貨/選擇權合計（TAIFEX OpenAPI）"""
    __tablename__ = "raw_options_inst_fo"
    __table_args__ = (UniqueConstraint("date", "institution", name="uq_opt_inst_fo"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False, index=True)
    institution = Column(String(10), nullable=False)
    fut_buy_vol = Column(BigInteger, default=0)
    opt_buy_vol = Column(BigInteger, default=0)
    fut_buy_val = Column(BigInteger, default=0)
    opt_buy_val = Column(BigInteger, default=0)
    fut_sell_vol = Column(BigInteger, default=0)
    opt_sell_vol = Column(BigInteger, default=0)
    fut_sell_val = Column(BigInteger, default=0)
    opt_sell_val = Column(BigInteger, default=0)
    fut_net_vol = Column(BigInteger, default=0)
    opt_net_vol = Column(BigInteger, default=0)
    fut_net_val = Column(BigInteger, default=0)
    opt_net_val = Column(BigInteger, default=0)
    fut_oi_long = Column(BigInteger, default=0)
    opt_oi_long = Column(BigInteger, default=0)
    fut_oi_long_val = Column(BigInteger, default=0)
    opt_oi_long_val = Column(BigInteger, default=0)
    fut_oi_short = Column(BigInteger, default=0)
    opt_oi_short = Column(BigInteger, default=0)
    fut_oi_short_val = Column(BigInteger, default=0)
    opt_oi_short_val = Column(BigInteger, default=0)
    fut_oi_net = Column(BigInteger, default=0)
    opt_oi_net = Column(BigInteger, default=0)
    fut_oi_net_val = Column(BigInteger, default=0)
    opt_oi_net_val = Column(BigInteger, default=0)
    created_at = Column(DateTime, server_default=func.now())


class RawOptionsLargeTraders(Base):
    """大額交易人選擇權未平倉（TAIFEX OpenAPI /OpenInterestOfLargeTradersOptions）"""
    __tablename__ = "raw_options_large_traders"
    __table_args__ = (UniqueConstraint("date", "contract", "call_put", "settlement_month", "trader_type", name="uq_opt_lt"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False, index=True)
    contract = Column(String(20), nullable=False, index=True)
    contract_name = Column(String(50))
    call_put = Column(String(10), nullable=False)
    settlement_month = Column(String(10), nullable=False)
    trader_type = Column(String(5), nullable=False)
    top5_buy = Column(BigInteger, default=0)
    top5_sell = Column(BigInteger, default=0)
    top10_buy = Column(BigInteger, default=0)
    top10_sell = Column(BigInteger, default=0)
    market_oi = Column(BigInteger, default=0)
    created_at = Column(DateTime, server_default=func.now())


class RawPutCallRatio(Base):
    """臺指選擇權 Put/Call 比（TAIFEX OpenAPI /PutCallRatio，22 交易日）"""
    __tablename__ = "raw_put_call_ratio"
    __table_args__ = (UniqueConstraint("date", name="uq_pcr_date"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False, index=True)
    put_volume = Column(BigInteger, default=0)
    call_volume = Column(BigInteger, default=0)
    pc_volume_ratio = Column(Float)
    put_oi = Column(BigInteger, default=0)
    call_oi = Column(BigInteger, default=0)
    pc_oi_ratio = Column(Float)
    created_at = Column(DateTime, server_default=func.now())


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
