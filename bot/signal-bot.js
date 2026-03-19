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
  const now = Date.now();
  const WATCH_EXPIRY_MS = 24 * 60 * 60 * 1000; // WATCH signals vervallen na 24h

  for (const sig of signals) {
    // WATCH signals: verwijder na 24h
    if (sig.type === 'WATCH') {
      const sigAge = now - (sig.id || 0);
      if (sigAge < WATCH_EXPIRY_MS) {
        stillActive.push(sig);
      } else {
        console.log(`  ⏰ WATCH ${sig.coin} verlopen (>24h) — verwijderd`);
      }
      continue;
    }

    if (resolvedIds.has(sig.id)) {
      // Al afgesloten, niet meer tonen
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

TAAK: Analyseer de 1H en 4H charts en geef maximaal 5 trading setups.

REGELS:
- Gebruik ALLEEN de exacte prijzen uit de data hierboven
- Geef ZOWEL BUY als SELL signalen op basis van de technische analyse:
  * BUY als: uptrend op 4H, prijs boven EMA20/EMA50, RSI < 70, bullish momentum
  * SELL als: downtrend op 4H, prijs onder EMA20/EMA50, RSI > 60, bearish momentum, of RSI overbought (>70)
- Forceer een eerlijke mix: als meerdere coins bearish zijn, geef SELL — niet alleen BUY
- Alleen signalen met duidelijke technische setup op zowel 1H als 4H
- Type: "BUY" of "SELL" (geen WATCH)
- Entry: dichtbij huidige prijs
- TP en SL gebaseerd op technische levels (EMA, 24h high/low)
- Risk/Reward minimaal 1:2
- Maximaal 1 signaal per coin
- Note: Nederlandse uitleg met exacte technische reden (vermeld RSI waarde, trend richting, EMA positie)

Geef ALLEEN een geldige JSON array terug, niets anders:
[{"coin":"BTC/USD","type":"BUY","entry":"83200","tp":"88000","sl":"81500","note":"4H trend bullish boven EMA50, RSI 52 niet overbought."},{"coin":"ETH/USD","type":"SELL","entry":"2050","tp":"1900","sl":"2120","note":"4H bearish onder EMA20, RSI 72 overbought, volume dalend."}]`;

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

  if (!res.ok) {
    const errBody = await res.text().catch(() => '(geen body)');
    console.error(`❌ Claude API HTTP fout: ${res.status} ${res.statusText}`);
    console.error(`   Response body: ${errBody.slice(0, 500)}`);
    if (res.status === 401) console.error('   → CLAUDE_API_KEY is ongeldig of verlopen!');
    if (res.status === 429) console.error('   → Rate limit bereikt. Probeer later opnieuw.');
    if (res.status === 400) console.error('   → Slecht verzoek, controleer model naam en parameters.');
    throw new Error(`Claude API error: ${res.status}`);
  }

  const data = await res.json();
  console.log(`   Claude stop_reason: ${data?.stop_reason}`);
  console.log(`   Claude usage: input=${data?.usage?.input_tokens} output=${data?.usage?.output_tokens} tokens`);

  const raw = data?.content?.[0]?.text || '';
  if (!raw) {
    console.error('❌ Claude gaf een lege response terug!');
    console.error('   Volledige API response:', JSON.stringify(data, null, 2).slice(0, 1000));
    return [];
  }

  console.log(`   Claude raw output (eerste 300 tekens): ${raw.slice(0, 300)}`);
  const cleaned = raw.replace(/```json/gi, '').replace(/```/g, '').trim();

  try {
    const signals = JSON.parse(cleaned);
    if (!Array.isArray(signals)) {
      console.error('❌ Claude gaf geen array terug, maar:', typeof signals);
      console.error('   Volledige output:', cleaned.slice(0, 500));
      return [];
    }
    console.log(`✅ Claude genereerde ${signals.length} signalen`);
    return signals.slice(0, 5);
  } catch (parseErr) {
    console.error('❌ JSON parse fout:', parseErr.message);
    console.error('   Volledige ruwe output:', cleaned.slice(0, 800));
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

  if (!res.ok) {
    const errBody = await res.text().catch(() => '(geen body)');
    console.error(`❌ Claude brief HTTP fout: ${res.status} ${res.statusText}`);
    console.error(`   Response body: ${errBody.slice(0, 300)}`);
    throw new Error(`Claude brief error: ${res.status}`);
  }

  const data = await res.json();
  const raw = data?.content?.[0]?.text || '';
  if (!raw) {
    console.error('❌ Claude brief gaf lege response terug');
    return { date: dateStr, focus: 'Marktupdate', risk: 'Neutraal', btc_structure: summary.split('\n')[0], eth_flows: '', top_narratives: ['BTC','ETH','Alts','Macro'], macro_impact: '', whale_flows: '', funding_oi: '', volatility_outlook: '', full_report: summary };
  }

  const cleaned = raw.replace(/```json/gi, '').replace(/```/g, '').trim();
  try {
    return JSON.parse(cleaned);
  } catch (parseErr) {
    console.error('❌ Market brief JSON parse fout:', parseErr.message);
    console.error('   Ruwe output:', cleaned.slice(0, 400));
    return { date: dateStr, focus: 'Marktupdate', risk: 'Neutraal', btc_structure: summary.split('\n')[0], eth_flows: '', top_narratives: ['BTC','ETH','Alts','Macro'], macro_impact: '', whale_flows: '', funding_oi: '', volatility_outlook: '', full_report: summary };
  }
}

// ── MAIN ───────────────────────────────────────────────────────────────────
(async () => {
  try {
    console.log('🚀 Signal Bot gestart —', new Date().toUTCString());

    if (!CLAUDE_API_KEY) {
      console.error('❌ CLAUDE_API_KEY is niet ingesteld als GitHub Secret!');
      console.error('   Ga naar: GitHub → Settings → Secrets → New secret → naam: CLAUDE_API_KEY');
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
    console.log(`✅ Prijzen opgehaald: BTC $${priceMap['bitcoin']?.toLocaleString()} | ETH $${priceMap['ethereum']?.toLocaleString()} | SOL $${priceMap['solana']?.toLocaleString()}`);

    // 3. Check bestaande trades op TP/SL
    console.log('📊 Actieve trades checken op TP/SL...');
    const activeSignals = checkAndResolveSignals(existingSignals, priceMap);
    const activeTrades  = activeSignals.filter(s => s.type !== 'WATCH');
    console.log(`✅ ${activeTrades.length} trades nog actief`);

    console.log(`📊 Actieve trades: ${activeTrades.length}/${MAX_ACTIVE_TRADES} slots bezet`);

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

    // 5. Bewaar ALLEEN actieve signalen (max MAX_ACTIVE_TRADES)
    const toSave = finalSignals.slice(0, MAX_ACTIVE_TRADES);
    writeJson(signalsPath, toSave);
    console.log(`💾 ${toSave.length} actieve signalen opgeslagen → signals.json`);
    if (toSave.length === 0) {
      console.warn('⚠️  signals.json is leeg opgeslagen! Controleer de logs hierboven voor de oorzaak.');
    }

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
