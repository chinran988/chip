/**
 * TPEx 上櫃分點全自動採集 v2（2026-07-14 驗證，破解新版 Cloudflare Turnstile）
 *
 * 前提：必須在「本機 Chrome」的 TPEx brokerBS 頁面 console 注入執行
 *   1. list_connected_browsers 確認連對本機（isLocal 會誤判跨機，用 switch_browser 讓使用者在正確那台點 Connect）
 *   2. 導航到 https://www.tpex.org.tw/zh-tw/mainboard/trading/info/brokerBS.html
 *   3. 確認頁面左側 Cloudflare 框顯示綠色「成功!」（Turnstile 已過）
 *   4. 注入本腳本 → 背景自走，資料即時入庫 CHIP 後端
 *
 * 機制：每支 turnstile.reset() 取新 token（一次性）→ POST brokerBS 帶 cf-turnstile-response
 *       → 解析 tables[1] 分點 → 組 CSV → POST localhost:8001/api/admin/collect/tpex-csv
 * 進度：window.__tpexJob（i/total/done/empty/fail/saved/running/failCodes）
 * 間隔：30±5 秒（與 BSR 一致）
 */
(async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));

  // ── 目標日期：預設當日；台灣時間 <16:00 取前一天（TPEx 下午4時才提供當日）；window.__tpexDate 可覆蓋 'YYYY-MM-DD'
  let DATE_ISO;
  if (window.__tpexDate) {
    DATE_ISO = window.__tpexDate;
  } else {
    const tw = new Date(Date.now() + 8 * 3600000);
    if (tw.getUTCHours() < 16) tw.setUTCDate(tw.getUTCDate() - 1);
    DATE_ISO = `${tw.getUTCFullYear()}-${String(tw.getUTCMonth()+1).padStart(2,'0')}-${String(tw.getUTCDate()).padStart(2,'0')}`;
  }
  const DATE_ROC = DATE_ISO.replace(/-/g, '/'); // 新版 brokerBS 接受西元 YYYY/MM/DD

  const EP = code => `https://www.tpex.org.tw/www/zh-tw/afterTrading/brokerBS?code=${code}&date=${DATE_ROC}&id=`;
  const BACKEND = 'http://localhost:8001/api/admin/collect/tpex-csv';
  const APIKEY = 'change-me-to-a-long-random-string';

  // ── 拉當日上櫃清單（OpenAPI 全部證券 → 篩 4碼個股 + 00開頭ETF）
  const q = await fetch('https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes', { credentials: 'include' });
  const arr = await q.json();
  const seen = new Set(), list = [];
  for (const x of arr) {
    const c = String(x.SecuritiesCompanyCode).trim();
    if ((/^\d{4}$/.test(c) || /^00\d{3,4}$/.test(c)) && !seen.has(c)) { seen.add(c); list.push(c); }
  }

  const J = { date: DATE_ISO, list, total: list.length, i: 0, done: 0, empty: 0, fail: 0,
              saved: 0, running: true, failCodes: [], startedAt: new Date().toISOString(), lastCode: null };
  window.__tpexJob = J;

  async function getToken() {
    turnstile.reset();
    for (let k = 0; k < 40; k++) { await sleep(500); const t = turnstile.getResponse(); if (t && t.length > 50) return t; }
    return null;
  }

  async function fetchOne(code) {
    for (let attempt = 1; attempt <= 3; attempt++) {
      const tok = await getToken();
      if (!tok) { if (attempt < 3) { await sleep(1500); continue; } return { err: 'no-token' }; }
      const r = await fetch(EP(code), { method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'Referer': location.href },
        body: 'cf-turnstile-response=' + encodeURIComponent(tok) });
      const j = await r.json();
      const data = (j.tables && j.tables[1] && j.tables[1].data) || [];
      if (data.length) return { data };
      if (j.stat && /無交易/.test(j.stat)) return { empty: true };
      if (attempt < 3) { await sleep(1500); continue; } // 逾時等 → retry
      return { err: (j.stat || 'unknown').slice(0, 20) };
    }
  }

  async function step() {
    if (!J.running || J.i >= J.list.length) { J.running = false; J.finishedAt = new Date().toISOString(); return; }
    const code = J.list[J.i]; J.lastCode = code;
    try {
      const res = await fetchOne(code);
      if (res.data) {
        const csv = '序號,券商,價格,買進股數,賣出股數\n' +
          res.data.map(row => `"${row[0]}","${row[1]}","${row[2]}","${row[3]}","${row[4]}"`).join('\n');
        const br = await fetch(BACKEND, { method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-API-Key': APIKEY },
          body: JSON.stringify({ date: DATE_ISO, code, csv_text: csv }) });
        const bj = await br.json();
        if (bj.ok) { J.done++; J.saved += bj.saved || 0; } else { J.fail++; J.failCodes.push(code); }
      } else if (res.empty) { J.empty++; }
      else { J.fail++; J.failCodes.push(code); }
    } catch (e) { J.fail++; J.failCodes.push(code); }
    J.i++;
    setTimeout(step, 30000 + (Math.random() * 10000 - 5000)); // 30±5 秒
  }
  step();
  console.log(`[TPEx] 啟動：日期=${DATE_ISO}，標的=${J.total} 支，間隔 30±5 秒`);
  return `STARTED date=${DATE_ISO} total=${J.total}`;
})();
