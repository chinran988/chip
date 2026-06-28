import requests, sys, json
sys.stdout.reconfigure(encoding='utf-8')
base = 'https://openapi.taifex.com.tw/v1'

endpoints = [
    '/MarketDataOfMajorInstitutionalTradersDetailsOfCallsAndPutsBytheDate',
    '/MarketDataOfMajorInstitutionalTradersDividedByFuturesAndOptionsBytheDate',
    '/OpenInterestOfLargeTradersOptions',
    '/PutCallRatio',
    '/FinalSettlementPriceIndexOptions',
]
for ep in endpoints:
    r = requests.get(f'{base}{ep}', timeout=30)
    try:
        data = json.loads(r.content.decode('utf-8'))
        count = len(data) if isinstance(data, list) else 1
        first = data[0] if isinstance(data, list) and data else data
        keys = list(first.keys()) if isinstance(first, dict) else []
        sample = json.dumps(first, ensure_ascii=False)[:200] if first else ''
        print(f'\n=== {ep} ===')
        print(f'  count={count}  keys={keys}')
        print(f'  sample: {sample}')
    except Exception as e:
        print(f'\n=== {ep} ===  ERROR: {e}  status={r.status_code}')
