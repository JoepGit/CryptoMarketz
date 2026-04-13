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
prompt = f"""You are the lead analyst at ZIMR Capital. Write the daily market brief for {today} in plain English prose — no bullet points, no headers, no JSON, no structure. Just a flowing written summary like a senior analyst would send to members every morning.

Write 4-5 paragraphs covering:
1. Overall market: what happened today, total market cap, general mood
2. BTC: exact price, what it did, key levels to watch
3. ETH and notable altcoins: what moved, what didn't, any divergences
4. Macro context: what's driving things (rates, geopolitics, regulation, sentiment)
5. What to watch next: key catalysts, risks, what would change the picture

RULES:
- English only. No Dutch, no German.
- Always use numerals: $72,544 not "seventy two thousand", 1.3% not "one point three percent"
- Tone: sharp, confident, trader-to-trader. Like a Bloomberg note, not a chatbot.
- No filler phrases. Every sentence should add information.
- Do NOT use bullet points, headers, or any formatting. Pure prose paragraphs only.

═══ LIVE MARKET DATA ═══
{market_block}

Top gainers 24h: {', '.join(gainers)}
Top losers 24h:  {', '.join(losers)}

Total crypto market cap: ${total_mcap}T ({mcap_chg:+.2f}% 24h)
24h volume: ${total_vol}B | BTC dominance: {btc_dom}% | ETH dominance: {eth_dom}%

Funding rates: {funding_block}
Open interest: {oi_block}
Recent liquidations: {liq_block}
Fear & Greed: {fg_block}

Latest news:
{news_block}

Now write the brief. Plain prose, 4-5 paragraphs, no formatting."""

# ── 6. Claude API call ────────────────────────────────────────────────────
print("\n🤖 Generating brief with Claude...")
payload = json.dumps({
    "model": "claude-sonnet-4-20250514",
    "max_tokens": 3000,
    "system": "You are the lead analyst at ZIMR Capital. Write ONLY in English. ALWAYS use numerals for numbers — never spell them out ($72,544 not seventy two thousand, 1.3% not one point three percent). Keep every field short and punchy. Respond only with valid JSON.",
    "messages": [{"role": "user", "content": prompt}]
}).encode()

import time as _time

def call_claude(payload, api_key, max_retries=3):
    """Retry on 529/500/503 with backoff. Returns None if API stays down."""
    for attempt in range(1, max_retries + 1):
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
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            print(f"⚠️  HTTP {e.code} (attempt {attempt}/{max_retries}): {body[:120]}")
            if e.code in (529, 500, 503) and attempt < max_retries:
                wait = 45 * attempt  # 45s, 90s
                print(f"⏳ API overloaded — retrying in {wait}s...")
                _time.sleep(wait)
            elif e.code in (529, 500, 503):
                print("⚠️  API still overloaded — keeping existing brief, will retry tomorrow.")
                return None
            else:
                raise  # real errors (401, 400 etc) still crash loudly
    return None

data = call_claude(payload, api_key)
if data is None:
    print("✅ No update today — existing brief stays live.")
    import sys; sys.exit(0)

import re as _re
text = data['content'][0]['text'].strip()
text = _re.sub(r'^```[a-z]*\s*', '', text)
text = _re.sub(r'\s*```$', '', text)
text = text.strip()
print(f"Claude response preview: {text[:300]}")

brief = {
    "date": today,
    "body": text,
    "btc_price": market_data[0]['current_price'],
    "fg_value": fg_now['value'],
    "fg_label": fg_now['value_classification'],
}

os.makedirs('data', exist_ok=True)
with open('data/marketbrief.json', 'w') as f:
    json.dump(brief, f, indent=2)

print(f"\n✅ Brief ready! BTC: ${market_data[0]['current_price']:,} | Fear & Greed: {fg_now['value']} | BTC dom: {btc_dom}%")
