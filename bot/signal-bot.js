// bot/signal-bot.js — CryptoMarketz Smart Signal Bot
// - Max 5 actieve trades tegelijk
// - Gebruikt 1h + 4h Binance candles voor analyse
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
const BINANCE_PAIRS = {
  'BTC/USD':'BTCUSDT', 'ETH/USD':'ETHUSDT', 'SOL/USD':'SOLUSDT',
  'BNB/USD':'BNBUSDT', 'XRP/USD':'XRPUSDT'
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

// ── 2. Binance: 1h en 4h candles ──────────────────────────────────────────
async function fetchCandles(pair, interval, limit = 50) {
  const symbol = BINANCE_PAIRS[pair];
  if (!symbol) return [];
  try {
    const url = `https://api.binance.com/api/v3/klines?symbol=${symbol}&interval=${interval}&limit=${limit}`;
    const res = await fetch(url);
    if (!res.ok) return [];
    const raw = await res.json();
    return raw.map(c => ({
      time: c[0], open: parseFloat(c[1]), high: parseFloat(c[2]),
      low: parseFloat(c[3]), close: parseFloat(c[4]), volume: parseFloat(c[5])
    }));
  } catch { return []; }
}

// ── 3. Technische indicatoren berekenen ───────────────────────────────────
function calcEMA(closes, period) {
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
  const ema50  = calcEMA(closes, 50);
  const rsi    = calcRSI(closes);
  const high24 = Math.max(...highs.slice(-24));
  const low24  = Math.min(...lows.slice(-24));
  const volAvg = candles.slice(-10).reduce((s,c) => s + c.volume, 0) / 10;
  const volLast = candles[candles.length-1].volume;
  const volRatio = (volLast / volAvg).toFixed(2);
  const trend = last > ema20 && ema20 > ema50 ? 'BULLISH' : last < ema20 && ema20 < ema50 ? 'BEARISH' : 'SIDEWAYS';

  return `${label}: prijs $${last.toFixed(2)} | EMA20 $${ema20.toFixed(2)} | EMA50 $${ema50.toFixed(2)} | RSI ${rsi.toFixed(1)} | trend ${trend} | 24h high $${high24.toFixed(2)} | 24h low $${low24.toFixed(2)} | vol ratio ${volRatio}x`;
}

// ── 4. Check actieve trades op TP/SL ──────────────────────────────────────
function checkAndResolveSignals(signals, priceMap) {
  const resultsPath = path.join(process.cwd(), 'data', 'results.json');
  const results = readJson(resultsPath, []);
  const resolvedIds = new Set(results.map(r => r.id));
  const newResults = [];
  const stillActive = [];

  for (const sig of signals) {
    if (sig.type === 'WATCH' || resolvedIds.has(sig.id)) {
      stillActive.push(sig);
      continue;
    }

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
      stillActive.push(sig); // nog actief
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

  const prompt = `Je bent een professionele crypto trader voor CryptoMarketz.

LIVE MARKTDATA + TECHNISCHE ANALYSE (${new Date().toUTCString()}):
${summary}

TAAK: Analyseer de 1H en 4H charts en geef maximaal 5 trading setups met de BESTE kans van slagen.

REGELS:
- Gebruik ALLEEN de exacte prijzen uit de data hierboven
- Alleen signalen met duidelijke technische setup op 1H én 4H
- Type: "BUY" of "SELL" (geen WATCH — die nemen een slot in)
- Entry: dichtbij huidige prijs (realistisch)
- TP en SL gebaseerd op technische levels (24h high/low, EMA levels)
- Risk/Reward minimaal 1:2
- Maximaal 1 signaal per coin
- Note: korte Nederlandse uitleg met verwijzing naar technische reden (EMA, RSI, trend)

Geef ALLEEN een geldige JSON array terug, niets anders:
[{"coin":"BTC/USD","type":"BUY","entry":"83200","tp":"88000","sl":"81500","note":"4H trend bullish boven EMA50, RSI niet overbought."}]`;

  const res = await fetch('https://api.anthropic.com/v1/messages', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'x-api-key': CLAUDE_API_KEY,
      'anthropic-version': '2023-06-01',
    },
    body: JSON.stringify({
      model: 'claude-haiku-4-5-20251001',
      max_tokens: 1024,
      messages: [{ role: 'user', content: prompt }],
    }),
  });

  if (!res.ok) throw new Error(`Claude API error: ${res.status}`);
  const data = await res.json();
  const raw = data?.content?.[0]?.text || '[]';
  const cleaned = raw.replace(/```json/gi, '').replace(/```/g, '').trim();
  try {
    const signals = JSON.parse(cleaned);
    if (!Array.isArray(signals)) throw new Error('Geen array');
    return signals.slice(0, 5); // nooit meer dan 5
  } catch {
    console.warn('Parse fout:', cleaned.slice(0, 200));
    return [];
  }
}

// ── 6. Market brief ────────────────────────────────────────────────────────
async function generateMarketBrief(marketData) {
  const now = new Date();
  const dateStr = now.toLocaleDateString('nl-NL', { weekday:'long', year:'numeric', month:'long', day:'numeric' });
  const summary = marketData.map(c => {
    const sym = COIN_SYMBOLS[c.id] || c.symbol.toUpperCase();
    const h24 = (c.price_change_percentage_24h || 0).toFixed(2);
    const vol = (c.total_volume / 1e9).toFixed(2);
    return `${sym}: $${c.current_price.toLocaleString()} | 24h ${h24}% | vol $${vol}B`;
  }).join('\n');

  const prompt = `Je bent hoofdanalist van CryptoMarketz. Schrijf een dagelijkse marktbrief in het Nederlands voor ${dateStr}.

LIVE MARKTDATA — gebruik UITSLUITEND deze prijzen, verzin niets:
${summary}

Geef ALLEEN een geldig JSON object terug, geen markdown:
{"date":"${dateStr}","focus":"één zin primaire focus","risk":"risk regime 3-5 woorden","btc_structure":"2-3 zinnen BTC met exacte prijs","eth_flows":"2-3 zinnen ETH met exacte prijs","top_narratives":["n1","n2","n3","n4"],"macro_impact":"2-3 zinnen macro","whale_flows":"2-3 zinnen whale flows op basis van volume","funding_oi":"2-3 zinnen funding verwachting","volatility_outlook":"2-3 zinnen volatiliteit","full_report":"4-6 zinnen volledig overzicht met exacte prijzen"}`;

  const res = await fetch('https://api.anthropic.com/v1/messages', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'x-api-key': CLAUDE_API_KEY,
      'anthropic-version': '2023-06-01',
    },
    body: JSON.stringify({ model: 'claude-haiku-4-5-20251001', max_tokens: 2048, messages: [{ role: 'user', content: prompt }] }),
  });

  if (!res.ok) throw new Error(`Claude brief error: ${res.status}`);
  const data = await res.json();
  const raw = data?.content?.[0]?.text || '{}';
  const cleaned = raw.replace(/```json/gi, '').replace(/```/g, '').trim();
  try {
    return JSON.parse(cleaned);
  } catch {
    return { date: dateStr, focus: 'Marktupdate', risk: 'Neutraal', btc_structure: summary.split('\n')[0], eth_flows: '', top_narratives: ['BTC','ETH','Alts','Macro'], macro_impact: '', whale_flows: '', funding_oi: '', volatility_outlook: '', full_report: summary };
  }
}

// ── MAIN ───────────────────────────────────────────────────────────────────
(async () => {
  try {
    if (!CLAUDE_API_KEY) throw new Error('CLAUDE_API_KEY niet ingesteld');

    const signalsPath = path.join(process.cwd(), 'data', 'signals.json');

    // 1. Laad bestaande actieve signalen
    const existingSignals = readJson(signalsPath, []);
    console.log(`📂 ${existingSignals.length} bestaande signalen geladen`);

    // 2. Haal live prijzen op
    console.log('🔍 CoinGecko prijzen ophalen...');
    const marketData = await fetchMarketData();
    const priceMap = {};
    for (const c of marketData) priceMap[c.id] = c.current_price;
    console.log(`✅ Prijzen: BTC $${priceMap['bitcoin']?.toLocaleString()}`);

    // 3. Check bestaande trades op TP/SL
    console.log('📊 Actieve trades checken op TP/SL...');
    const activeSignals = checkAndResolveSignals(existingSignals, priceMap);
    const activeTrades  = activeSignals.filter(s => s.type !== 'WATCH');
    console.log(`✅ ${activeTrades.length} trades nog actief`);

    // 4. Alleen nieuwe signalen als er ruimte is
    let finalSignals = activeSignals;
    const slotsOpen = MAX_ACTIVE_TRADES - activeTrades.length;

    if (slotsOpen > 0) {
      console.log(`🆓 ${slotsOpen} slot(s) vrij — 1H/4H charts ophalen...`);

      // Haal candles op voor alle coins
      const candleData = {};
      for (const c of marketData) {
        const sym = COIN_SYMBOLS[c.id];
        if (!sym) continue;
        const [c1h, c4h] = await Promise.all([
          fetchCandles(sym, '1h', 50),
          fetchCandles(sym, '4h', 50),
        ]);
        candleData[sym] = {
          '1h': summarizeCandles(c1h, '1H'),
          '4h': summarizeCandles(c4h, '4H'),
        };
        console.log(`  📈 ${sym}: ${candleData[sym]['1h'].split('|')[2]?.trim()} | ${candleData[sym]['4h'].split('|')[2]?.trim()}`);
      }

      console.log('🤖 Claude analyseert setups...');
      const newSignals = await generateSignals(marketData, candleData);

      // Dedupliceer: geen nieuwe trade voor coin die al actief is
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

    // 5. Bewaar max 50 signalen (actief + recent afgesloten voor weergave)
    const toSave = finalSignals.slice(0, 50);
    writeJson(signalsPath, toSave);
    console.log(`💾 ${toSave.length} signalen → signals.json`);

    // 6. Market brief genereren
    console.log('📝 Market brief genereren...');
    const brief = await generateMarketBrief(marketData);
    writeJson(path.join(process.cwd(), 'data', 'marketbrief.json'), brief);
    console.log('✅ Market brief → marketbrief.json');

  } catch (err) {
    console.error('❌ Bot fout:', err.message);
    process.exit(1);
  }
})();
