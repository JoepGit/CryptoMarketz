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

# ── 2. Bybit public API: funding rates + open interest ────────────────────
print("\n📈 Fetching Bybit funding rates + OI...")
funding_lines = []
oi_lines = []
BYBIT_PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]

for pair in BYBIT_PAIRS:
    try:
        ticker = json.loads(fetch(
            f"https://api.bybit.com/v5/market/tickers?category=linear&symbol={pair}"
        ))
        item = ticker["result"]["list"][0]
        fr = round(float(item.get("fundingRate", 0)) * 100, 4)
        oi_val = float(item.get("openInterest", 0))
        sym = pair.replace("USDT", "")
        price = next((c["current_price"] for c in market_data if SYMBOLS.get(c["id"]) == sym), 1)
        oi_usd = round(oi_val * price / 1e9, 2)
        funding_lines.append(f"{pair}: {fr:+.4f}%")
        oi_lines.append(f"{pair}: OI ${oi_usd}B")
    except Exception as e:
        funding_lines.append(f"{pair}: n/a ({e})")
        oi_lines.append(f"{pair}: n/a")

print("💥 Fetching liquidations from Bybit...")
liq_lines = []
for pair in ["BTCUSDT", "ETHUSDT"]:
    try:
        liq = json.loads(fetch(
            f"https://api.bybit.com/v5/market/recent-trade?category=linear&symbol={pair}&limit=200"
        ))
        trades = liq["result"]["list"]
        buy_vol  = sum(float(t["size"]) for t in trades if t.get("side") == "Buy")
        sell_vol = sum(float(t["size"]) for t in trades if t.get("side") == "Sell")
        sym = pair.replace("USDT", "")
        price = next((c["current_price"] for c in market_data if SYMBOLS.get(c["id"]) == sym), 1)
        liq_lines.append(
            f"{pair}: buy vol {round(buy_vol * price / 1e6, 1)}M USD | sell vol {round(sell_vol * price / 1e6, 1)}M USD (last 200 trades)"
        )
    except Exception as e:
        liq_lines.append(f"{pair}: n/a ({e})")

funding_block = "\n".join(funding_lines)
oi_block      = "\n".join(oi_lines)
liq_block     = "\n".join(liq_lines) if liq_lines else "Not available"
print(f"✅ Funding: {funding_block}")

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
prompt = f"""You are the lead analyst at ZIMR Capital, writing the daily market brief for {today}.

CRITICAL: You MUST write ONLY in English. Every single word must be English. No Dutch, no other languages.
Each section must be at least 4-6 sentences. Use the exact prices and figures from the live data below.

═══ LIVE PRICE DATA — use ONLY these prices ═══
{market_block}

Top gainers 24h: {', '.join(gainers)}
Top losers 24h:  {', '.join(losers)}

═══ GLOBAL MARKET ═══
Total crypto market cap: ${total_mcap}T ({mcap_chg:+.2f}% 24h)
24h total volume: ${total_vol}B
BTC dominance: {btc_dom}% | ETH dominance: {eth_dom}%

═══ BYBIT FUTURES: FUNDING RATES ═══
{funding_block}
(positive = longs pay shorts = bullish sentiment, negative = shorts pay longs = bearish)

═══ BYBIT FUTURES: OPEN INTEREST ═══
{oi_block}

═══ RECENT TRADE VOLUME (proxy for liquidation pressure) ═══
{liq_block}

═══ FEAR & GREED INDEX ═══
{fg_block}

═══ LATEST NEWS ═══
{news_block}

INSTRUCTIONS:
- Write ENTIRELY in English — absolutely no Dutch words anywhere in the response
- Every section must be 4-6 sentences minimum, rich with analysis and context
- Reference exact prices, percentages and figures from the data above
- Analyse what the funding rates and OI mean for market direction
- Connect the news headlines to price action where relevant
- Write like a professional analyst briefing institutional traders

Return ONLY a valid JSON object, no markdown, no explanation:
{{
  "date": "{today}",
  "focus": "one sentence: primary market focus today based on the data",
  "risk": "risk regime in 4-6 words e.g. High Risk — Extreme Fear territory",
  "btc_structure": "4-6 sentences on BTC: exact current price, 24h and 7d performance, key support/resistance levels to watch, what the price action tells us about market structure, and what traders should do",
  "eth_flows": "4-6 sentences on ETH: exact price, performance vs BTC, volume analysis, Layer 2 context, and key levels",
  "top_narratives": [
    "Narrative 1: 2-3 sentence description of the most important theme driving markets today",
    "Narrative 2: 2-3 sentence description",
    "Narrative 3: 2-3 sentence description",
    "Narrative 4: 2-3 sentence description"
  ],
  "macro_impact": "4-6 sentences: macro context from the news, geopolitical factors, regulatory developments, and how they are impacting crypto sentiment and price action",
  "whale_flows": "4-6 sentences: analysis of trade volume data, what it reveals about leverage in the market, volume interpretation, and what large players appear to be doing",
  "funding_oi": "4-6 sentences: detailed analysis of the funding rates across pairs, what the open interest levels mean, whether the market is overleveraged, and trading implications",
  "volatility_outlook": "4-6 sentences: volatility assessment based on Fear & Greed index score, trade volumes, funding rates, and what kind of moves traders should prepare for in the next 24-48 hours",
  "full_report": "6-8 sentences: complete executive overview incorporating exact prices, Fear & Greed score, BTC dominance, key news catalysts, funding environment, and overall market outlook for the day"
}}"""

# ── 6. Claude API call ────────────────────────────────────────────────────
print("\n🤖 Generating brief with Claude...")
payload = json.dumps({
    "model": "claude-haiku-4-5-20251001",
    "max_tokens": 3000,
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

text = data['content'][0]['text'].strip()
if text.startswith('```'):
    text = '\n'.join(text.split('\n')[1:])
if text.endswith('```'):
    text = '\n'.join(text.split('\n')[:-1])

brief = json.loads(text.strip())
brief['date'] = today

os.makedirs('data', exist_ok=True)
with open('data/marketbrief.json', 'w') as f:
    json.dump(brief, f, indent=2)

print(f"\n✅ Brief ready! BTC: ${market_data[0]['current_price']:,} | Fear & Greed: {fg_now['value']} | BTC dom: {btc_dom}%")
