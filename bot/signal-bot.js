// bot/signal-bot.js
// CryptoMarketz — Automatische signal bot via Claude AI
// CoinGecko data → Claude analyseert → schrijft data/signals.json

import fetch from 'node-fetch';
import fs from 'fs';
import path from 'path';

const CLAUDE_API_KEY = process.env.CLAUDE_API_KEY;
const COINS = ['bitcoin', 'ethereum', 'solana', 'binancecoin', 'ripple'];
const COIN_SYMBOLS = {
  bitcoin: 'BTC/USD',
  ethereum: 'ETH/USD',
  solana: 'SOL/USD',
  binancecoin: 'BNB/USD',
  ripple: 'XRP/USD',
};

// ── 1. Haal marktdata op via CoinGecko (gratis, geen key nodig) ──────────────
async function fetchMarketData() {
  const ids = COINS.join(',');
  const url =
    `https://api.coingecko.com/api/v3/coins/markets` +
    `?vs_currency=usd&ids=${ids}&order=market_cap_desc` +
    `&per_page=10&page=1&sparkline=false&price_change_percentage=1h,24h,7d`;

  const res = await fetch(url);
  if (!res.ok) throw new Error(`CoinGecko error: ${res.status}`);
  return res.json();
}

// ── 2. Claude analyseert de markt en genereert signalen ──────────────────────
async function analyzeWithClaude(marketData) {
  const coinSummaries = marketData.map((c) => {
    const ch1h  = (c.price_change_percentage_1h_in_currency  || 0).toFixed(2);
    const ch24h = (c.price_change_percentage_24h             || 0).toFixed(2);
    const ch7d  = (c.price_change_percentage_7d_in_currency  || 0).toFixed(2);
    return (
      `${COIN_SYMBOLS[c.id] || c.symbol.toUpperCase()}: ` +
      `Prijs $${c.current_price.toLocaleString()}, ` +
      `1h: ${ch1h}%, 24h: ${ch24h}%, 7d: ${ch7d}%, ` +
      `Volume: $${(c.total_volume / 1e9).toFixed(2)}B, ` +
      `Mkt cap: $${(c.market_cap / 1e9).toFixed(1)}B`
    );
  });

  const prompt = `Je bent een professionele crypto trader en analist voor het CryptoMarketz platform.

Hier is de actuele marktdata (${new Date().toUTCString()}):
${coinSummaries.join('\n')}

Analyseer de markt en genereer trading signalen. Geef ALLEEN een geldig JSON array terug, geen uitleg of markdown erbuiten.

Regels:
- Genereer alleen signalen met een duidelijke technische setup
- Niet elke coin hoeft een signaal — alleen als er een echte reden is
- Type: "BUY", "SELL" of "WATCH"
- Entry, TP en SL gebaseerd op huidige prijs en momentum
- Risk/Reward minimaal 1:2
- Note: korte Nederlandse uitleg (max 1 zin)

JSON formaat:
[
  {
    "coin": "BTC/USD",
    "type": "BUY",
    "entry": "83200",
    "tp": "88000",
    "sl": "81500",
    "note": "Bullish momentum boven de 4H EMA, volume neemt toe."
  }
]

Geef alleen de JSON array terug, niets anders.`;

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
    const err = await res.text();
    throw new Error(`Claude API error: ${res.status} — ${err}`);
  }

  const data = await res.json();
  const raw = data?.content?.[0]?.text || '[]';

  const cleaned = raw.replace(/```json/gi, '').replace(/```/g, '').trim();

  try {
    const signals = JSON.parse(cleaned);
    if (!Array.isArray(signals)) throw new Error('Geen array teruggekomen');
    return signals;
  } catch (e) {
    console.warn('⚠️  Kon Claude response niet parsen:', cleaned);
    return [];
  }
}

// ── 3. Schrijf signals.json naar data/ map ────────────────────────────────────
function writeSignals(newSignals) {
  const outputPath = path.join(process.cwd(), 'data', 'signals.json');

  // Lees bestaande signalen in (max 50 bewaren)
  let existing = [];
  if (fs.existsSync(outputPath)) {
    try {
      existing = JSON.parse(fs.readFileSync(outputPath, 'utf8'));
    } catch {
      existing = [];
    }
  }

  // Voeg timestamp en uniek ID toe aan nieuwe signalen
  const stamped = newSignals.map((s) => ({
    id: Date.now() + Math.floor(Math.random() * 1000),
    coin: s.coin,
    type: s.type,
    entry: s.entry,
    tp: s.tp,
    sl: s.sl,
    note: s.note || '',
    timestamp: new Date().toISOString(),
    generated_at: new Date().toUTCString(),
  }));

  // Nieuwe signalen bovenaan, max 50 totaal
  const combined = [...stamped, ...existing].slice(0, 50);

  // Zorg dat de data/ map bestaat
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  fs.writeFileSync(outputPath, JSON.stringify(combined, null, 2), 'utf8');

  console.log(`✅ ${stamped.length} nieuwe signalen geschreven naar data/signals.json`);
  console.log(`📊 Totaal in bestand: ${combined.length} signalen`);
  stamped.forEach((s) => console.log(`   → ${s.type} ${s.coin} | Entry: ${s.entry} | TP: ${s.tp} | SL: ${s.sl}`));
}

// ── Main ──────────────────────────────────────────────────────────────────────
(async () => {
  try {
    if (!CLAUDE_API_KEY) throw new Error('CLAUDE_API_KEY is niet ingesteld in GitHub Secrets');

    console.log('🔍 Marktdata ophalen van CoinGecko...');
    const marketData = await fetchMarketData();
    console.log(`✅ Data voor ${marketData.length} coins ontvangen`);

    console.log('🤖 Claude analyseert de markt...');
    const signals = await analyzeWithClaude(marketData);
    console.log(`✅ ${signals.length} signalen gegenereerd`);

    writeSignals(signals);
  } catch (err) {
    console.error('❌ Bot fout:', err.message);
    process.exit(1);
  }
})();
