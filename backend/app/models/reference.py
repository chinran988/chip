from sqlalchemy import Column, String, Boolean, Date, Integer
from app.core.database import Base


class TradingCalendar(Base):
    __tablename__ = "trading_calendar"

    date = Column(Date, primary_key=True)
    is_trading_day = Column(Boolean, nullable=False, default=True)
    note = Column(String(100))  # 假日名稱或颱風停市備注


class Stock(Base):
    __tablename__ = "stocks"

    stock_id = Column(String(10), primary_key=True)  # e.g. "2330"
    name = Column(String(100), nullable=False)
    market = Column(String(10), nullable=False, index=True)  # twse / otc
    industry = Column(String(50))
    industry_code = Column(String(10))
    isin = Column(String(20))
    listed_date = Column(Date)
    is_active = Column(Boolean, default=True, index=True)
    source = Column(String(20), default="twse")  # twse / sinopac / manual


class BrokerBranch(Base):
    __tablename__ = "broker_branches"

    branch_id = Column(String(10), primary_key=True)  # e.g. "9200"
    broker_name = Column(String(100))
    branch_name = Column(String(100))
    region = Column(String(50))
    city = Column(String(50))
