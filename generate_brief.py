import os, json, urllib.request, urllib.error, xml.etree.ElementTree as ET
from datetime import date

today = str(date.today())
api_key = os.environ['CLAUDE_API_KEY']

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.read()

# ── 1. CoinGecko: prices, gainers/losers, dominance, global mcap ─────────
print("📊 Fetching CoinGecko data...")
COINS = "bitcoin,ethereum,solana,binancecoin,ripple,cardano,avalanche-2,chainlink,polkadot,uniswap"
market_data = json.loads(fetch(
    f"https://api.coingecko.com/api/v3/coins/markets"
    f"?vs_currency=usd&ids={COINS}&order=market_cap_desc"
    f"&per_page=10&page=1&sparkline=false&price_change_percentage=1h,24h,7d"
))

global_data = json.loads(fetch("https://api.coingecko.com/api/v3/global"))["data"]
btc_dom    = round(global_data["market_cap_percentage"]["btc"], 1)
eth_dom    = round(global_data["market_cap_percentage"]["eth"], 1)
total_mcap = round(global_data["total_market_cap"]["usd"] / 1e12, 2)
total_vol  = round(global_data["total_volume"]["usd"] / 1e9, 1)
mcap_chg   = round(global_data.get("market_cap_change_percentage_24h_usd", 0), 2)

SYMBOLS = {
    "bitcoin":"BTC","ethereum":"ETH","solana":"SOL","binancecoin":"BNB",
    "ripple":"XRP","cardano":"ADA","avalanche-2":"AVAX","chainlink":"LINK",
    "polkadot":"DOT","uniswap":"UNI"
}

price_lines = []
for c in market_data:
    sym = SYMBOLS.get(c["id"], c["symbol"].upper())
    p   = c["current_price"]
    h1  = round(c.get("price_change_percentage_1h_in_currency") or 0, 2)
    h24 = round(c.get("price_change_percentage_24h") or 0, 2)
    h7d = round(c.get("price_change_percentage_7d_in_currency") or 0, 2)
    vol = round(c["total_volume"] / 1e9, 2)
    price_lines.append(
        f"{sym}/USD: ${p:,} | 1h {h1:+.2f}% | 24h {h24:+.2f}% | 7d {h7d:+.2f}% | vol ${vol}B"
    )

sorted_24h = sorted(market_data, key=lambda c: c.get("price_change_percentage_24h") or 0)
losers  = [f"{SYMBOLS.get(c['id'],c['symbol'].upper())} {round(c.get('price_change_percentage_24h') or 0,2):+.2f}%" for c in sorted_24h[:3]]
gainers = [f"{SYMBOLS.get(c['id'],c['symbol'].upper())} {round(c.get('price_change_percentage_24h') or 0,2):+.2f}%" for c in sorted_24h[-3:][::-1]]

market_block = "\n".join(price_lines)
print(f"✅ {len(market_data)} coins | BTC dom {btc_dom}% | Total mcap ${total_mcap}T")

# ── 2. Funding / OI — not available from GitHub Actions (APIs blocked) ──────
print("\n📈 Funding/OI APIs not reachable from GitHub Actions — skipping...")
funding_block = "Not available (API blocked from GitHub Actions servers)"
oi_block      = "Not available (API blocked from GitHub Actions servers)"
liq_block     = "Not available (API blocked from GitHub Actions servers)"
print("⚠️  Funding/OI data skipped — Claude will analyse based on price action only")

# ── 3. Fear & Greed Index ─────────────────────────────────────────────────
print("\n😨 Fetching Fear & Greed...")
try:
    fg_data = json.loads(fetch("https://api.alternative.me/fng/?limit=2"))
    fg_now  = fg_data["data"][0]
    fg_prev = fg_data["data"][1]
    fg_block = (
        f"Today: {fg_now['value']} ({fg_now['value_classification']}) | "
        f"Yesterday: {fg_prev['value']} ({fg_prev['value_classification']})"
    )
    print("✅ " + fg_block)
except Exception as e:
    fg_block = "Not available"
    fg_now = {"value": "N/A"}
    print("⚠️  Fear & Greed failed:", e)

# ── 4. News (CoinDesk + Cointelegraph RSS) ────────────────────────────────
print("\n📰 Fetching news...")
news_items = []

def parse_rss(url, source, max_items=5):
    try:
        root = ET.fromstring(fetch(url))
        for item in root.findall(".//item")[:max_items]:
            title = item.findtext("title", "").strip()
            if title:
                news_items.append(f"[{source}] {title}")
    except Exception as e:
        print(f"⚠️  {source} failed: {e}")

parse_rss("https://www.coindesk.com/arc/outboundfeeds/rss/", "CoinDesk")
parse_rss("https://cointelegraph.com/rss", "Cointelegraph")
news_block = "\n".join(news_items[:10]) if news_items else "Not available"
print(f"✅ {len(news_items)} news headlines")

# ── 5. Build prompt ───────────────────────────────────────────────────────
prompt = f"""LANGUAGE RULE — THIS IS MANDATORY: Write ONLY in English. Every word must be English. Never write in Dutch. Never write in German. English only.

You are the lead analyst at CryptoMarketz, writing the daily market brief for {today}.

CRITICAL REQUIREMENT: You MUST write ONLY in English. Every single word must be English. Do NOT use Dutch, German, or any other language under any circumstances.
Each section must be at least 4-6 sentences. Use the exact prices and figures from the live data below.

═══ LIVE PRICE DATA — use ONLY these prices ═══
{market_block}

Top gainers 24h: {', '.join(gainers)}
Top losers 24h:  {', '.join(losers)}

═══ GLOBAL MARKET ═══
Total crypto market cap: ${total_mcap}T ({mcap_chg:+.2f}% 24h)
24h total volume: ${total_vol}B
BTC dominance: {btc_dom}% | ETH dominance: {eth_dom}%

═══ BINANCE FUTURES: FUNDING RATES ═══
{funding_block}
(positive = longs pay shorts = bullish sentiment, negative = shorts pay longs = bearish)

═══ BINANCE FUTURES: OPEN INTEREST ═══
{oi_block}

═══ RECENT LIQUIDATIONS ═══
{liq_block}

═══ FEAR & GREED INDEX ═══
{fg_block}

═══ LATEST NEWS ═══
{news_block}

INSTRUCTIONS:
- Write ONLY in English. No Dutch words anywhere.
- Every section must be 5-7 sentences — detailed, analytical, professional.
- Use exact prices, percentages and figures from the data above.
- Funding/OI data unavailable — base leverage analysis on price action, Fear & Greed, and volume.
- Connect news headlines to price action where relevant.
- Write like a senior analyst briefing institutional traders.

Return ONLY valid JSON, no markdown, no backticks:
{{
  "date": "{today}",  // ENGLISH ONLY — example: March 25, 2026
  "focus": "one sentence: primary market focus today based on the data",
  "risk": "risk regime in 4-6 words e.g. High Risk — Extreme Fear territory",
  "btc_structure": "5-7 sentences: exact BTC price, 1h/24h/7d performance, key support and resistance levels, what price action and volume reveal about market structure, whether bulls or bears are in control, and what traders should watch",
  "eth_flows": "5-7 sentences: exact ETH price, performance vs BTC, 24h and 7d change, volume context, Layer 2 ecosystem context from news, key levels, and ETH/BTC ratio outlook",
  "top_narratives": [
    "Narrative 1: 3 sentence description of the most important theme driving markets today with specific data points",
    "Narrative 2: 3 sentence description with specific data points",
    "Narrative 3: 3 sentence description with specific data points",
    "Narrative 4: 3 sentence description with specific data points"
  ],
  "macro_impact": "5-7 sentences: macro context from the news, regulatory developments, geopolitical factors, how traditional markets affect crypto, Fed policy implications, DXY and risk-on/off sentiment, and macro outlook for next 48 hours",
  "whale_flows": "5-7 sentences: analysis of volume patterns across top coins, what volume data reveals about institutional vs retail participation, which coins show unusual volume, what gainers and losers tell us about rotation, and what large players appear to be positioning for",
  "funding_oi": "5-7 sentences: leverage and positioning assessment based on price action and Fear & Greed, whether market appears overleveraged, what extreme fear implies for reversals or continuation, liquidation risk assessment, and trading implications",
  "volatility_outlook": "5-7 sentences: volatility assessment based on Fear & Greed score, recent price action, volume patterns, upcoming catalysts from news, expected trading ranges for BTC and ETH, and specific risk management recommendations",
  "full_report": "7-9 sentences: complete executive overview with exact BTC price, ETH price, total market cap, Fear & Greed score, BTC dominance, top gainers and losers, key news catalysts, macro environment, market structure, and 24-48 hour outlook"
}}"""

# ── 6. Claude API call ────────────────────────────────────────────────────
print("\n🤖 Generating brief with Claude...")
payload = json.dumps({
    "model": "claude-sonnet-4-20250514",
    "max_tokens": 4096,
    "system": "You are a professional crypto market analyst writing for an English-speaking audience. ABSOLUTE RULE: Every single word in your response must be in English. Dutch is strictly forbidden. German is forbidden. Any non-English language is forbidden. If you write even one Dutch word, your response is invalid. Respond only with valid JSON.",
    "messages": [{"role": "user", "content": prompt}]
}).encode()

req = urllib.request.Request(
    "https://api.anthropic.com/v1/messages",
    data=payload,
    headers={
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01"
    }
)

try:
    with urllib.request.urlopen(req) as r:
        data = json.loads(r.read())
except urllib.error.HTTPError as e:
    print("HTTP Error:", e.code, e.read().decode())
    raise

import re as _re
text = data['content'][0]['text'].strip()
text = _re.sub(r'^```[a-z]*\s*', '', text)
text = _re.sub(r'\s*```$', '', text)
text = text.strip()
print(f"Claude response preview: {text[:200]}")
try:
    brief = json.loads(text)
except json.JSONDecodeError as e:
    print(f"❌ JSON parse error: {e}")
    print(f"Last 300 chars: {text[-300:]}")
    raise
brief['date'] = today

os.makedirs('data', exist_ok=True)
with open('data/marketbrief.json', 'w') as f:
    json.dump(brief, f, indent=2)

print(f"\n✅ Brief ready! BTC: ${market_data[0]['current_price']:,} | Fear & Greed: {fg_now['value']} | BTC dom: {btc_dom}%")
