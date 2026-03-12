import os, json, urllib.request, urllib.error, xml.etree.ElementTree as ET
from datetime import date

today = str(date.today())
api_key = os.environ['CLAUDE_API_KEY']

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.read()

# ── 1. CoinGecko: prijzen, gainers/losers, dominantie, global mcap ────────
print("📊 CoinGecko ophalen...")
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

# ── 2. Binance public API: funding rates + open interest ──────────────────
print("\n📈 Binance funding rates + OI ophalen...")
funding_lines = []
oi_lines = []
BINANCE_PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]

for pair in BINANCE_PAIRS:
    try:
        # Funding rate
        fr_data = json.loads(fetch(
            f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={pair}"
        ))
        fr = round(float(fr_data["lastFundingRate"]) * 100, 4)
        funding_lines.append(f"{pair}: {fr:+.4f}%")
    except Exception as e:
        funding_lines.append(f"{pair}: n/a")

    try:
        # Open Interest
        oi_data = json.loads(fetch(
            f"https://fapi.binance.com/fapi/v1/openInterest?symbol={pair}"
        ))
        oi = round(float(oi_data["openInterest"]))
        sym = pair.replace("USDT","")
        # get price for USD value
        price = next((c["current_price"] for c in market_data if SYMBOLS.get(c["id"]) == sym), 1)
        oi_usd = round(oi * price / 1e9, 2)
        oi_lines.append(f"{pair}: {oi:,} contracts (${oi_usd}B)")
    except Exception as e:
        oi_lines.append(f"{pair}: n/a")

# Binance 24h liquidaties
print("💥 Liquidaties ophalen...")
liq_lines = []
for pair in ["BTCUSDT", "ETHUSDT"]:
    try:
        liq_data = json.loads(fetch(
            f"https://fapi.binance.com/fapi/v1/allForceOrders?symbol={pair}&limit=100"
        ))
        long_liq  = sum(float(o["origQty"]) * float(o["price"]) for o in liq_data if o["side"] == "SELL")
        short_liq = sum(float(o["origQty"]) * float(o["price"]) for o in liq_data if o["side"] == "BUY")
        liq_lines.append(
            f"{pair}: longs geliquideerd ${round(long_liq/1e6,1)}M | shorts geliquideerd ${round(short_liq/1e6,1)}M"
        )
    except Exception as e:
        liq_lines.append(f"{pair}: n/a")

funding_block = "\n".join(funding_lines)
oi_block      = "\n".join(oi_lines)
liq_block     = "\n".join(liq_lines) if liq_lines else "Niet beschikbaar"
print(f"✅ Funding rates: {funding_block}")
print(f"✅ Open Interest: {oi_block}")

# ── 3. Fear & Greed Index ─────────────────────────────────────────────────
print("\n😨 Fear & Greed ophalen...")
try:
    fg_data = json.loads(fetch("https://api.alternative.me/fng/?limit=2"))
    fg_now  = fg_data["data"][0]
    fg_prev = fg_data["data"][1]
    fg_block = (
        f"Vandaag: {fg_now['value']} ({fg_now['value_classification']}) | "
        f"Gisteren: {fg_prev['value']} ({fg_prev['value_classification']})"
    )
    print("✅ " + fg_block)
except Exception as e:
    fg_block = "Niet beschikbaar"
    print("⚠️  Fear & Greed mislukt:", e)

# ── 4. Nieuws (CoinDesk + Cointelegraph RSS) ──────────────────────────────
print("\n📰 Nieuws ophalen...")
news_items = []

def parse_rss(url, source, max_items=5):
    try:
        root = ET.fromstring(fetch(url))
        for item in root.findall(".//item")[:max_items]:
            title = item.findtext("title", "").strip()
            if title:
                news_items.append(f"[{source}] {title}")
    except Exception as e:
        print(f"⚠️  {source} mislukt: {e}")

parse_rss("https://www.coindesk.com/arc/outboundfeeds/rss/", "CoinDesk")
parse_rss("https://cointelegraph.com/rss", "Cointelegraph")
news_block = "\n".join(news_items[:10]) if news_items else "Niet beschikbaar"
print(f"✅ {len(news_items)} nieuwsberichten")

# ── 5. Prompt samenstellen ────────────────────────────────────────────────
prompt = f"""Je bent hoofdanalist van CryptoMarketz. Schrijf een dagelijkse marktbrief in het Nederlands voor {today}.

═══ LIVE PRIJSDATA — gebruik UITSLUITEND deze prijzen ═══
{market_block}

Top gainers 24h: {', '.join(gainers)}
Top losers 24h:  {', '.join(losers)}

═══ GLOBAL MARKT ═══
Totale crypto market cap: ${total_mcap}T ({mcap_chg:+.2f}% 24h)
24h totaal volume: ${total_vol}B
BTC dominantie: {btc_dom}% | ETH dominantie: {eth_dom}%

═══ BINANCE FUTURES: FUNDING RATES ═══
{funding_block}
(positief = longs betalen shorts = bullish sentiment, negatief = shorts betalen longs = bearish)

═══ BINANCE FUTURES: OPEN INTEREST ═══
{oi_block}

═══ RECENTE LIQUIDATIES ═══
{liq_block}

═══ FEAR & GREED INDEX ═══
{fg_block}

═══ ACTUEEL NIEUWS ═══
{news_block}

INSTRUCTIES:
- Gebruik ALLEEN prijzen uit de data hierboven — verzin geen andere getallen
- Verwerk funding rates en OI in funding_oi sectie
- Verwerk liquidaties in whale_flows
- Verwerk nieuws in macro_impact en top_narratives
- Schrijf professioneel Nederlands

Geef ALLEEN een geldig JSON object terug, geen markdown, geen uitleg:
{{
  "date": "{today}",
  "focus": "één zin: primaire focus vandaag",
  "risk": "risk regime in 3-5 woorden",
  "btc_structure": "2-3 zinnen over BTC met exacte prijs en key levels",
  "eth_flows": "2-3 zinnen over ETH met exacte prijs",
  "top_narratives": ["narrative 1", "narrative 2", "narrative 3", "narrative 4"],
  "macro_impact": "2-3 zinnen macro context gebaseerd op nieuws",
  "whale_flows": "2-3 zinnen gebaseerd op liquidaties en volume",
  "funding_oi": "2-3 zinnen gebaseerd op de funding rates en OI hierboven",
  "volatility_outlook": "2-3 zinnen verwachte volatiliteit op basis van Fear & Greed en liquidaties",
  "full_report": "4-6 zinnen volledig overzicht met exacte prijzen, Fear & Greed score en funding rates"
}}"""

# ── 6. Claude API call ────────────────────────────────────────────────────
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

print(f"\n✅ Brief klaar! BTC: ${market_data[0]['current_price']:,} | Fear & Greed: {fg_now['value']} | BTC dom: {btc_dom}%")
