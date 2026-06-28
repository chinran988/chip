import sys
sys.stdout.reconfigure(encoding='utf-8')

# test import
from app.models.raw import RawOptionsChain, RawOptionsInstitutional, RawOptionsInstFO, RawOptionsLargeTraders, RawPutCallRatio
from app.collectors.taifex_options import TaifexOptionsCollector
from app.api.v1.options import router
from app.core.database import init_db, SessionLocal

print('imports OK')

# init DB (create tables)
init_db()
print('DB init OK')

# run collector
db = SessionLocal()
col = TaifexOptionsCollector(db)
results = col.collect()
print('collect results:', results)
db.close()

# verify DB
from sqlalchemy import text
db2 = SessionLocal()
for tbl in ['raw_options_chain','raw_options_institutional','raw_options_inst_fo','raw_options_large_traders','raw_put_call_ratio']:
    cnt = db2.execute(text(f'SELECT COUNT(*) FROM {tbl}')).scalar()
    print(f'  {tbl}: {cnt} rows')
db2.close()
