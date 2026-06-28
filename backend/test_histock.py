import requests, io, sys, re
sys.stdout.reconfigure(encoding='utf-8')

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120',
    'Accept-Language': 'zh-TW,zh;q=0.9',
    'Referer': 'https://histock.tw/',
}

# 測試 HiStock 周選擇權頁面
url = 'https://histock.tw/stock/option.aspx?m=week'
r = requests.get(url, headers=headers, timeout=20)
print('status:', r.status_code, '  len:', len(r.text))

# 確認資料在 HTML 裡
import pandas as pd
tables = pd.read_html(io.StringIO(r.text))
print(f'pandas 找到 {len(tables)} 個 table')
for i, df in enumerate(tables):
    if df.shape[0] > 20:
        print(f'\ntable[{i}] shape={df.shape}')
        print(df.iloc[:5, :10].to_string())
        print('...')
        print('欄位:', list(df.columns[:10]))
        break
