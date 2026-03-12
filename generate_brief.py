import os, json, urllib.request, urllib.error, xml.etree.ElementTree as ET
from datetime import date

today = str(date.today())
api_key = os.environ['CLAUDE_API_KEY']

def fetch(url):
    with urllib.request.urlopen(url, timeout=10) as r:
        return r.read()

# ── 1. Live prijzen + top gainers/losers (CoinGecko) ──────────────────────
print("📊 CoinGecko prijzen ophalen...")
COINS = "bitcoin,ethereum,solana,binancecoin,ripple,cardano,avalanche-2,chainlink,polkadot,uniswap"
cg_url = (
    f"https://api.coingecko.com/api/v3/coins/markets"
    f"?vs_currency=usd&ids={COINS}&order=market_cap_desc"
    f"&per_page=10&page=1&sparkline=false&price_change_percentage=1h,24h,7d"
)
market_data = json.loads(fetch(cg_url))

SYMBOLS = {
    "bitcoin":"BTC","ethereum":"ETH","solana":"SOL","binancecoin":"BNB",
    "ripple":"XRP","cardano":"ADA","avalanche-2":"AVAX","chainlink":"LINK",
    "polkadot":"DOT","uniswap":"UNI"
}

price_lines = []
for c in market_data:
    sym  = SYMBOLS.get(c["id"], c["symbol"].upper())
    p    = c["current_price"]
    h1   = round(c.get("price_change_percentage_1h_in_currency") or 0, 2)
    h24  = round(c.get("price_change_percentage_24h") or 0, 2)
    h7d  = round(c.get("price_change_percentage_7d_in_currency") or 0, 2)
    vol  = round(c["total_volume"] / 1e9, 2)
    mc   = round(c["market_cap"] / 1e9, 1)
    price_lines.append(
        f"{sym}/USD: ${p:,} | 1h {h1:+.2f}% | 24h {h24:+.2f}% | 7d {h7d:+.2f}% | vol ${vol}B | mcap ${mc}B"
    )

# Top gainers / losers op 24h
sorted_24h = sorted(market_data, key=lambda c: c.get("price_change_percentage_24h") or 0)
losers  = [f"{SYMBOLS.get(c['id'], c['symbol'].upper())} {round(c.get('price_change_percentage_24h') or 0,2):+.2f}%" for c in sorted_24h[:3]]
gainers = [f"{SYMBOLS.get(c['id'], c['symbol'].upper())} {round(c.get('price_change_percentage_24h') or 0,2):+.2f}%" for c in sorted_24h[-3:][::-1]]

market_block = "\n".join(price_lines)
print("✅ Prijzen:\n" + market_block)

# ── 2. Fear & Greed Index ─────────────────────────────────────────────────
print("\n😨 Fear & Greed ophalen...")
try:
    fg_data = json.loads(fetch("https://api.alternative.me/fng/?limit=2"))
    fg_now  = fg_data["data"][0]
    fg_prev = fg_data["data"][1]
    fg_block = (
        f"Vandaag: {fg_now['value']} ({fg_now['value_classification']}) | "
        f"Gisteren: {fg_prev['value']} ({fg_prev['value_classification']})"
    )
    print("✅ Fear & Greed: " + fg_block)
except Exception as e:
    fg_block = "Niet beschikbaar"
    print("⚠️  Fear & Greed mislukt:", e)

# ── 3. Crypto nieuws (CoinDesk RSS + Cointelegraph RSS) ───────────────────
print("\n📰 Nieuws ophalen...")
news_items = []

def parse_rss(url, source, max_items=5):
    try:
        xml_data = fetch(url)
        root = ET.fromstring(xml_data)
        items = root.findall(".//item")[:max_items]
        for item in items:
            title = item.findtext("title", "").strip()
            if title:
                news_items.append(f"[{source}] {title}")
    except Exception as e:
        print(f"⚠️  {source} RSS mislukt: {e}")

parse_rss("https://www.coindesk.com/arc/outboundfeeds/rss/", "CoinDesk")
parse_rss("https://cointelegraph.com/rss", "Cointelegraph")

if news_items:
    news_block = "\n".join(news_items[:10])
    print(f"✅ {len(news_items)} nieuwsberichten gevonden")
else:
    news_block = "Geen nieuws beschikbaar"
    print("⚠️  Geen nieuws")

# ── 4. Prompt samenstellen ────────────────────────────────────────────────
prompt = f"""Je bent hoofdanalist van CryptoMarketz. Schrijf een dagelijkse marktbrief in het Nederlands voor {today}.

═══ LIVE PRIJSDATA (gebruik UITSLUITEND deze prijzen) ═══
{market_block}

Top gainers 24h: {', '.join(gainers)}
Top losers 24h:  {', '.join(losers)}

═══ FEAR & GREED INDEX ═══
{fg_block}

═══ ACTUEEL CRYPTO NIEUWS ═══
{news_block}

INSTRUCTIES:
- Gebruik ALLEEN de prijzen uit de data hierboven — verzin geen andere getallen
- Baseer whale_flows en funding_oi op het volume en de koersbewegingen hierboven
- Verwerk het nieuws in je macro_impact en top_narratives
- Schrijf in het Nederlands, professioneel maar begrijpelijk

Geef ALLEEN een geldig JSON object terug, geen markdown, geen uitleg buiten de JSON:
{{
  "date": "{today}",
  "focus": "één zin: primaire focus vandaag",
  "risk": "risk regime in 3-5 woorden",
  "btc_structure": "2-3 zinnen over BTC structuur met exacte prijs",
  "eth_flows": "2-3 zinnen over ETH met exacte prijs",
  "top_narratives": ["narrative 1", "narrative 2", "narrative 3", "narrative 4"],
  "macro_impact": "2-3 zinnen macro context gebaseerd op het nieuws",
  "whale_flows": "2-3 zinnen whale/exchange flows gebaseerd op volume data",
  "funding_oi": "2-3 zinnen funding rates gebaseerd op Fear & Greed en koersbewegingen",
  "volatility_outlook": "2-3 zinnen verwachte volatiliteit",
  "full_report": "4-6 zinnen volledig overzicht met exacte prijzen en Fear & Greed score"
}}"""

# ── 5. Claude API call ────────────────────────────────────────────────────
print("\n🤖 Claude brief genereren...")
payload = json.dumps({
    "model": "claude-haiku-4-5-20251001",
    "max_tokens": 1500,
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

print(f"\n✅ Brief geschreven! BTC: ${market_data[0]['current_price']:,} | Fear & Greed: {fg_block}")
