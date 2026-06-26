"""Stock list + search endpoint."""
from fastapi import APIRouter, Query, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.reference import Stock

router = APIRouter(prefix="/api/v1", tags=["stocks"])


@router.get("/stocks")
def list_stocks(
    market: str | None = Query(None, description="twse / otc"),
    q: str | None = Query(None, description="search by id or name"),
    db: Session = Depends(get_db),
):
    query = db.query(Stock).filter(Stock.is_active == True)
    if market:
        query = query.filter(Stock.market == market)
    if q:
        query = query.filter(
            (Stock.stock_id.like(f"%{q}%")) | (Stock.name.like(f"%{q}%"))
        )
    stocks = query.order_by(Stock.stock_id).limit(500).all()
    return {
        "count": len(stocks),
        "stocks": [{"stock_id": s.stock_id, "name": s.name, "market": s.market, "industry": s.industry}
                   for s in stocks],
    }


@router.get("/stocks/{stock_id}")
def get_stock(stock_id: str, db: Session = Depends(get_db)):
    s = db.get(Stock, stock_id)
    if not s:
        from fastapi import HTTPException
        raise HTTPException(404, f"Stock {stock_id} not found")
    return {"stock_id": s.stock_id, "name": s.name, "market": s.market,
            "industry": s.industry, "isin": s.isin, "source": s.source}
