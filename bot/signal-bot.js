// bot/signal-bot.js — CryptoMarketz Smart Signal Bot
// - Max 5 actieve trades tegelijk
// - Gebruikt 1h + 4h CoinGecko OHLC candles voor analyse
// - Checkt elk uur of TP/SL geraakt is
// - Schrijft signals.json, results.json, marketbrief.json

import fetch from 'node-fetch';
import fs from 'fs';
import path from 'path';

const CLAUDE_API_KEY = process.env.CLAUDE_API_KEY;
const MAX_ACTIVE_TRADES = 5;

const COINS = ['bitcoin','ethereum','solana','binancecoin','ripple'];
const COIN_SYMBOLS = {
  bitcoin:'BTC/USD', ethereum:'ETH/USD', solana:'SOL/USD',
  binancecoin:'BNB/USD', ripple:'XRP/USD'
};

// ── Helpers ────────────────────────────────────────────────────────────────
function readJson(filePath, fallback) {
  try {
    if (fs.existsSync(filePath)) return JSON.parse(fs.readFileSync(filePath, 'utf8'));
  } catch {}
  return fallback;
}

function writeJson(filePath, data) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, JSON.stringify(data, null, 2), 'utf8');
}

// ── 1. CoinGecko: live prijzen ─────────────────────────────────────────────
async function fetchMarketData() {
  const ids = COINS.join(',');
  const url = `https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids=${ids}&order=market_cap_desc&per_page=10&page=1&sparkline=false&price_change_percentage=1h,24h,7d`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`CoinGecko error: ${res.status}`);
  return res.json();
}

// ── 2. CoinGecko: OHLC candles (werkt vanuit GitHub Actions) ──────────────
// days=1 → ~1h candles, days=7 → ~4h candles
async function fetchCandles(coinId, intervalLabel) {
  const days = intervalLabel === '1h' ? 1 : 7;
  try {
    const url = `https://api.coingecko.com/api/v3/coins/${coinId}/ohlc?vs_currency=usd&days=${days}`;
    const res = await fetch(url);
    if (!res.ok) {
      console.warn(`  ⚠️  CoinGecko OHLC fout voor ${coinId} (${intervalLabel}): ${res.status}`);
      return [];
    }
    const raw = await res.json();
    // CoinGecko OHLC: [timestamp, open, high, low, close]
    return raw.map(c => ({
      time: c[0], open: c[1], high: c[2], low: c[3], close: c[4], volume: 0
    }));
  } catch (e) {
    console.warn(`  ⚠️  OHLC fetch fout ${coinId}: ${e.message}`);
    return [];
  }
}

// ── 3. Technische indicatoren berekenen ───────────────────────────────────
function calcEMA(closes, period) {
  if (closes.length < period) return closes[closes.length - 1];
  const k = 2 / (period + 1);
  let ema = closes[0];
  for (let i = 1; i < closes.length; i++) ema = closes[i] * k + ema * (1 - k);
  return ema;
}

function calcRSI(closes, period = 14) {
  if (closes.length < period + 1) return 50;
  let gains = 0, losses = 0;
  for (let i = closes.length - period; i < closes.length; i++) {
    const diff = closes[i] - closes[i - 1];
    if (diff > 0) gains += diff; else losses -= diff;
  }
  const rs = gains / (losses || 0.0001);
  return 100 - 100 / (1 + rs);
}

function summarizeCandles(candles, label) {
  if (!candles.length) return `${label}: geen data`;
  const closes = candles.map(c => c.close);
  const highs  = candles.map(c => c.high);
  const lows   = candles.map(c => c.low);
  const last   = closes[closes.length - 1];
  const ema20  = calcEMA(closes, 20);
  const ema50  = calcEMA(closes, Math.min(50, closes.length));
  const rsi    = calcRSI(closes);
  const high24 = Math.max(...highs.slice(-Math.min(24, highs.length)));
  const low24  = Math.min(...lows.slice(-Math.min(24, lows.length)));
  const trend  = last > ema20 && ema20 > ema50 ? 'BULLISH' : last < ema20 && ema20 < ema50 ? 'BEARISH' : 'SIDEWAYS';

  return `${label}: prijs $${last.toFixed(2)} | EMA20 $${ema20.toFixed(2)} | EMA50 $${ema50.toFixed(2)} | RSI ${rsi.toFixed(1)} | trend ${trend} | 24h high $${high24.toFixed(2)} | 24h low $${low24.toFixed(2)}`;
}

// ── 4. Check actieve trades op TP/SL ──────────────────────────────────────
function checkAndResolveSignals(signals, priceMap) {
  const resultsPath = path.join(process.cwd(), 'data', 'results.json');
  const results = readJson(resultsPath, []);
  const resolvedIds = new Set(results.map(r => r.id));
  const newResults = [];
  const stillActive = [];
  const now = Date.now();
  const WATCH_EXPIRY_MS = 24 * 60 * 60 * 1000;

  for (const sig of signals) {
    if (sig.type === 'WATCH') {
      const sigAge = now - (sig.id || 0);
      if (sigAge < WATCH_EXPIRY_MS) {
        stillActive.push(sig);
      } else {
        console.log(`  ⏰ WATCH ${sig.coin} verlopen (>24h) — verwijderd`);
      }
      continue;
    }

    if (resolvedIds.has(sig.id)) continue;

    const coinKey = Object.keys(COIN_SYMBOLS).find(k => COIN_SYMBOLS[k] === sig.coin);
    const price = priceMap[coinKey];
    if (!price) { stillActive.push(sig); continue; }

    const entry = parseFloat(sig.entry);
    const tp    = parseFloat(sig.tp);
    const sl    = parseFloat(sig.sl);
    if (!entry || !tp || !sl) { stillActive.push(sig); continue; }

    let outcome = null;
    if (sig.type === 'BUY') {
      if (price >= tp) outcome = 'win';
      else if (price <= sl) outcome = 'loss';
    } else if (sig.type === 'SELL') {
      if (price <= tp) outcome = 'win';
      else if (price >= sl) outcome = 'loss';
    }

    if (outcome) {
      const pnlPct = outcome === 'win'
        ? (((tp - entry) / entry) * 100).toFixed(2)
        : (((sl - entry) / entry) * 100).toFixed(2);
      const pnlFormatted = (outcome === 'win' ? '+' : '') + pnlPct + '%';
      newResults.push({
        id: sig.id, coin: sig.coin, type: sig.type,
        entry: sig.entry, tp: sig.tp, sl: sig.sl,
        result: outcome, pnl: pnlFormatted,
        resolved_price: price,
        signal_date: sig.timestamp,
        resolved_at: new Date().toISOString(),
      });
      console.log(`  📊 ${sig.coin} ${sig.type} → ${outcome.toUpperCase()} (${pnlFormatted})`);
    } else {
      stillActive.push(sig);
    }
  }

  if (newResults.length > 0) {
    const combined = [...newResults, ...results].slice(0, 500);
    writeJson(resultsPath, combined);
    console.log(`✅ ${newResults.length} trades afgesloten → results.json`);
  } else {
    if (!fs.existsSync(resultsPath)) writeJson(resultsPath, []);
    console.log('ℹ️  Geen TP/SL hits deze run');
  }

  return stillActive;
}

// ── 5. Claude: nieuwe signalen genereren ──────────────────────────────────
async function generateSignals(marketData, candleData) {
  const summary = marketData.map(c => {
    const sym  = COIN_SYMBOLS[c.id] || c.symbol.toUpperCase();
    const ch1h = (c.price_change_percentage_1h_in_currency || 0).toFixed(2);
    const ch24 = (c.price_change_percentage_24h || 0).toFixed(2);
    const ch7d = (c.price_change_percentage_7d_in_currency || 0).toFixed(2);
    const c1h  = candleData[sym]?.['1h'] || 'geen data';
    const c4h  = candleData[sym]?.['4h'] || 'geen data';
    return `${sym}: $${c.current_price.toLocaleString()} | 1h ${ch1h}% | 24h ${ch24}% | 7d ${ch7d}%\n  1H chart: ${c1h}\n  4H chart: ${c4h}`;
  }).join('\n\n');

  const prompt = `You are a professional crypto trader for CryptoMarketz. Your goal is a HIGH WIN RATE — only take trades with strong conviction.

LIVE MARKET DATA + TECHNICAL ANALYSIS (${new Date().toUTCString()}):
${summary}

TASK: Analyse the 1H and 4H charts. Only generate a signal if you are genuinely confident it is a winner. If nothing looks convincing, return an empty array [].

STRICT RULES:
- Quality over quantity — it is BETTER to return 0-2 signals than 5 forced ones
- Only signal when ALL conditions align: trend, EMA alignment, RSI, and clear risk/reward
- BUY only when: 4H uptrend, price above EMA20 AND EMA50, RSI between 40-65, clear support below
- SELL only when: 4H downtrend, price below EMA20 AND EMA50, RSI above 60, clear resistance above
- Minimum Risk/Reward ratio: 1:2.5 (TP must be at least 2.5x the distance to SL)
- Entry: at or very close to current price
- TP and SL based on strong technical levels (EMA, 24h high/low, key structure)
- Maximum 1 signal per coin
- Position size: always 1/3 of available capital (include this in note)
- Note: explain the exact technical reason in English, mention the 1/3 position size

IF NO CLEAR HIGH-CONVICTION SETUP EXISTS: return exactly []

Return ONLY a valid JSON array, nothing else, no markdown:
[{"coin":"BTC/USD","type":"BUY","entry":"83200","tp":"88000","sl":"81500","note":"4H bullish above EMA50, RSI 52, clear support at 81500. Use 1/3 position size."}]`;

  const res = await fetch('https://api.anthropic.com/v1/messages', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'x-api-key': CLAUDE_API_KEY,
      'anthropic-version': '2023-06-01',
    },
    body: JSON.stringify({
      model: 'claude-sonnet-4-20250514',
      max_tokens: 1024,
      messages: [{ role: 'user', content: prompt }],
    }),
  });

  if (!res.ok) {
    const errBody = await res.text().catch(() => '(geen body)');
    console.error(`❌ Claude API HTTP fout: ${res.status} ${res.statusText}`);
    console.error(`   Response body: ${errBody.slice(0, 500)}`);
    if (res.status === 401) console.error('   → CLAUDE_API_KEY is ongeldig of verlopen!');
    if (res.status === 429) console.error('   → Rate limit bereikt.');
    throw new Error(`Claude API error: ${res.status}`);
  }

  const data = await res.json();
  console.log(`   Claude stop_reason: ${data?.stop_reason}`);
  console.log(`   Claude usage: input=${data?.usage?.input_tokens} output=${data?.usage?.output_tokens} tokens`);

  const raw = data?.content?.[0]?.text || '';
  if (!raw) {
    console.error('❌ Claude gaf lege response terug');
    return [];
  }

  console.log(`   Claude raw output (eerste 300 tekens): ${raw.slice(0, 300)}`);

  // Robuuste JSON extractie: pak alleen het JSON array gedeelte
  const jsonMatch = raw.match(/\[[\s\S]*\]/);
  if (!jsonMatch) {
    console.error('❌ Geen JSON array gevonden in Claude output');
    console.error('   Volledige output:', raw.slice(0, 500));
    return [];
  }

  try {
    const signals = JSON.parse(jsonMatch[0]);
    if (!Array.isArray(signals)) {
      console.error('❌ Claude gaf geen array terug');
      return [];
    }
    console.log(`✅ Claude genereerde ${signals.length} signalen`);
    return signals.slice(0, 5);
  } catch (parseErr) {
    console.error('❌ JSON parse fout:', parseErr.message);
    console.error('   Geëxtraheerde JSON:', jsonMatch[0].slice(0, 500));
    return [];
  }
}

// Market brief is generated by generate_brief.py (runs daily at 07:00 UTC via separate workflow)

// ── MAIN ───────────────────────────────────────────────────────────────────
(async () => {
  try {
    console.log('🚀 Signal Bot gestart —', new Date().toUTCString());

    if (!CLAUDE_API_KEY) {
      console.error('❌ CLAUDE_API_KEY is niet ingesteld als GitHub Secret!');
      throw new Error('CLAUDE_API_KEY niet ingesteld');
    }
    console.log(`✅ CLAUDE_API_KEY aanwezig (eerste 8 tekens: ${CLAUDE_API_KEY.slice(0, 8)}...)`);

    const signalsPath = path.join(process.cwd(), 'data', 'signals.json');

    // 1. Laad bestaande actieve signalen
    const existingSignals = readJson(signalsPath, []);
    console.log(`📂 ${existingSignals.length} bestaande signalen geladen`);

    // 2. Haal live prijzen op
    console.log('🔍 CoinGecko prijzen ophalen...');
    let marketData;
    try {
      marketData = await fetchMarketData();
    } catch (cgErr) {
      console.error('❌ CoinGecko fetch mislukt:', cgErr.message);
      throw cgErr;
    }
    const priceMap = {};
    for (const c of marketData) priceMap[c.id] = c.current_price;
    console.log(`✅ Prijzen: BTC $${priceMap['bitcoin']?.toLocaleString()} | ETH $${priceMap['ethereum']?.toLocaleString()} | SOL $${priceMap['solana']?.toLocaleString()}`);

    // 3. Check bestaande trades op TP/SL
    console.log('📊 Actieve trades checken op TP/SL...');
    const activeSignals = checkAndResolveSignals(existingSignals, priceMap);
    const activeTrades  = activeSignals.filter(s => s.type !== 'WATCH');
    console.log(`📊 Actieve trades: ${activeTrades.length}/${MAX_ACTIVE_TRADES} slots bezet`);

    // 4. Alleen nieuwe signalen als er ruimte is
    let finalSignals = activeSignals;
    const slotsOpen = MAX_ACTIVE_TRADES - activeTrades.length;

    if (slotsOpen > 0) {
      console.log(`🆓 ${slotsOpen} slot(s) vrij — CoinGecko OHLC candles ophalen...`);

      const candleData = {};
      for (const c of marketData) {
        const sym = COIN_SYMBOLS[c.id];
        if (!sym) continue;
        // Gebruik coinId voor CoinGecko OHLC
        const [c1h, c4h] = await Promise.all([
          fetchCandles(c.id, '1h'),
          fetchCandles(c.id, '4h'),
        ]);
        candleData[sym] = {
          '1h': summarizeCandles(c1h, '1H'),
          '4h': summarizeCandles(c4h, '4H'),
        };
        console.log(`  📈 ${sym} — 1H: ${c1h.length} candles | 4H: ${c4h.length} candles | trend: ${candleData[sym]['4h'].includes('BULLISH') ? '🟢 BULLISH' : candleData[sym]['4h'].includes('BEARISH') ? '🔴 BEARISH' : '🟡 SIDEWAYS'}`);
      }

      console.log('🤖 Claude analyseert setups...');
      const newSignals = await generateSignals(marketData, candleData);

      const activeCoins = new Set(activeTrades.map(s => s.coin));
      const filteredNew = newSignals
        .filter(s => !activeCoins.has(s.coin))
        .slice(0, slotsOpen)
        .map(s => ({
          id: Date.now() + Math.floor(Math.random() * 10000),
          coin: s.coin, type: s.type, entry: s.entry, tp: s.tp, sl: s.sl,
          note: s.note || '',
          timestamp: new Date().toISOString(),
          generated_at: new Date().toUTCString(),
          source: 'claude-bot',
        }));

      finalSignals = [...filteredNew, ...activeSignals];
      console.log(`✅ ${filteredNew.length} nieuwe signalen toegevoegd`);
      filteredNew.forEach(s => console.log(`   → ${s.type} ${s.coin} | Entry: ${s.entry} | TP: ${s.tp} | SL: ${s.sl}`));
    } else {
      console.log(`⏸️  Alle ${MAX_ACTIVE_TRADES} slots bezet — geen nieuwe signalen`);
    }

    // 5. Bewaar actieve signalen
    const toSave = finalSignals.slice(0, MAX_ACTIVE_TRADES);
    writeJson(signalsPath, toSave);
    console.log(`💾 ${toSave.length} actieve signalen → signals.json`);
    if (toSave.length === 0) {
      console.warn('⚠️  signals.json is leeg opgeslagen! Controleer de logs hierboven.');
    }

    console.log('ℹ️  Market brief is generated separately by generate_brief.py — skipping');

  } catch (err) {
    console.error('❌ Bot fout:', err.message);
    process.exit(1);
  }
})();
