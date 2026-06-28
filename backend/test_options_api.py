import sys, json
sys.stdout.reconfigure(encoding='utf-8')
from app.core.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()

# /api/v1/options/expiries
from app.api.v1.options import get_expiries, get_support_resistance, get_chain, get_institutional, get_put_call_ratio, get_large_traders
expiries = get_expiries(date_str=None, contract='TXO', db=db)
print('expiries:', len(expiries['expiries']), '個到期月份:', expiries['expiries'][:6])

# /api/v1/options/support-resistance
first_exp = expiries['expiries'][0] if expiries['expiries'] else None
sr = get_support_resistance(date_str=None, contract='TXO', expiry=first_exp, db=db)
print('support-resistance:', len(sr['data']), '個履約價, date=', sr['date'])

# /api/v1/options/institutional
inst = get_institutional(date_str=None, db=db)
print('institutional call_put:', len(inst['call_put']), 'rows, fut_opt:', len(inst['fut_opt']))

# /api/v1/options/put-call-ratio
pcr = get_put_call_ratio(days=22, db=db)
print('pcr:', len(pcr['data']), '天 P/C比')

# /api/v1/options/large-traders
lt = get_large_traders(date_str=None, contract='TXO', db=db)
print('large-traders:', len(lt['data']), '行')

# chain (first expiry)
chain = get_chain(date_str=None, contract='TXO', expiry=first_exp, db=db)
print('chain:', len(chain['rows']), '筆 expiry=', first_exp)
db.close()
