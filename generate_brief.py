import os, json, urllib.request, urllib.error
from datetime import date

today = str(date.today())
api_key = os.environ['CLAUDE_API_KEY']

# ── 1. Live prijzen ophalen van CoinGecko ──────────────────────────────────
COINS = "bitcoin,ethereum,solana,binancecoin,ripple"
cg_url = (
    f"https://api.coingecko.com/api/v3/coins/markets"
    f"?vs_currency=usd&ids={COINS}&order=market_cap_desc"
    f"&per_page=10&page=1&sparkline=false&price_change_percentage=1h,24h,7d"
)
with urllib.request.urlopen(cg_url) as r:
    market_data = json.loads(r.read())

SYMBOLS = {
    "bitcoin": "BTC", "ethereum": "ETH", "solana": "SOL",
    "binancecoin": "BNB", "ripple": "XRP"
}

lines = []
for c in market_data:
    sym  = SYMBOLS.get(c["id"], c["symbol"].upper())
    p    = c["current_price"]
    h1   = round(c.get("price_change_percentage_1h_in_currency")  or 0, 2)
    h24  = round(c.get("price_change_percentage_24h")             or 0, 2)
    h7d  = round(c.get("price_change_percentage_7d_in_currency")  or 0, 2)
    vol  = round(c["total_volume"] / 1e9, 2)
    lines.append(
        f"{sym}/USD: prijs ${p:,}  |  1h {h1:+.2f}%  24h {h24:+.2f}%  7d {h7d:+.2f}%  vol ${vol}B"
    )

market_block = "\n".join(lines)
print("Live marktdata:\n" + market_block)

# ── 2. Prompt met echte prijzen ────────────────────────────────────────────
prompt = f"""Je bent hoofdanalist van CryptoMarketz. Schrijf een dagelijkse marktbrief in het Nederlands voor {today}.

LIVE MARKTDATA (gebruik UITSLUITEND deze prijzen — verzin geen andere getallen):
{market_block}

Geef ALLEEN een geldig JSON object terug, geen markdown, geen uitleg:
{{
  "date": "{today}",
  "focus": "één zin: primaire focus vandaag",
  "risk": "risk regime in 3-5 woorden",
  "btc_structure": "2-3 zinnen over BTC — gebruik de exacte prijs hierboven",
  "eth_flows": "2-3 zinnen over ETH — gebruik de exacte prijs hierboven",
  "top_narratives": ["narrative 1", "narrative 2", "narrative 3", "narrative 4"],
  "macro_impact": "2-3 zinnen macro context",
  "whale_flows": "2-3 zinnen whale/exchange flows op basis van volume hierboven",
  "funding_oi": "2-3 zinnen funding rates verwachting",
  "volatility_outlook": "2-3 zinnen verwachte volatiliteit",
  "full_report": "4-6 zinnen volledig overzicht met exacte prijzen uit de data hierboven"
}}"""

# ── 3. Claude API call ─────────────────────────────────────────────────────
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

print('Brief geschreven met live prijzen:', {c["id"]: c["current_price"] for c in market_data})
