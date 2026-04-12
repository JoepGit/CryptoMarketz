import urllib.request, json, datetime, os

# Fetch Polymarket markets
try:
    req = urllib.request.Request(
        'https://gamma-api.polymarket.com/markets?limit=40&active=true&order=volume24hr&ascending=false&closed=false',
        headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        markets = json.loads(r.read())
    print(f"Fetched {len(markets)} markets")
except Exception as e:
    print(f"Fetch failed: {e}")
    exit(1)

def get_prob(m):
    try:
        prices = json.loads(m['outcomePrices']) if isinstance(m.get('outcomePrices'), str) else m.get('outcomePrices', [])
        if prices: return round(float(prices[0]) * 100)
    except: pass
    if m.get('lastTradePrice'): return round(float(m['lastTradePrice']) * 100)
    return 50

def get_change(m):
    if m.get('oneDayPriceChange'): return round(float(m['oneDayPriceChange']) * 100, 1)
    if m.get('price24hChange'): return round(float(m['price24hChange']) * 100, 1)
    return 0

def fmt_vol(v):
    v = float(v or 0)
    if v >= 1e6: return f'${v/1e6:.1f}M'
    if v >= 1e3: return f'${v/1e3:.0f}K'
    return f'${v:.0f}'

processed = []
for m in markets:
    processed.append({
        'question': m.get('question', ''),
        'prob': max(1, min(99, get_prob(m))),
        'change': get_change(m),
        'vol24': fmt_vol(m.get('volume24hr', 0)),
        'slug': m.get('slug', '')
    })

movers = sorted(processed, key=lambda x: abs(x['change']), reverse=True)[:10]
top_vol = processed[:5]

movers_text = '\n'.join([
    f"- {m['question']} | {m['prob']}% | {'+' if m['change']>0 else ''}{m['change']}% today | Vol: {m['vol24']}"
    for m in movers
])
vol_text = '\n'.join([
    f"- {m['question']} | {m['prob']}% | Vol: {m['vol24']}"
    for m in top_vol
])

today = datetime.datetime.utcnow().strftime('%A %B %d, %Y')
prompt = f"""You are the ZIMR Capital market intelligence analyst. Write a sharp daily Polymarket briefing for {today}.

Top movers (24h):
{movers_text}

Highest volume:
{vol_text}

Write:
1. A punchy headline about what the market is saying today
2. 2-3 short paragraphs: biggest signals, what smart money is doing, any mispricings
3. A Watch List with 2-3 markets to track today and why

Direct, insightful, useful for crypto traders. No fluff."""

api_key = os.environ.get('ANTHROPIC_API_KEY', '')
if not api_key:
    print("No API key")
    exit(1)

try:
    payload = json.dumps({
        'model': 'claude-haiku-4-5-20251001',
        'max_tokens': 800,
        'messages': [{'role': 'user', 'content': prompt}]
    }).encode()
    req = urllib.request.Request(
        'https://api.anthropic.com/v1/messages',
        data=payload,
        headers={
            'Content-Type': 'application/json',
            'x-api-key': api_key,
            'anthropic-version': '2023-06-01'
        }
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        resp = json.loads(r.read())
    brief_text = resp['content'][0]['text']
    print("Brief generated!")
except Exception as e:
    print(f"Claude failed: {e}")
    exit(1)

os.makedirs('data', exist_ok=True)
output = {
    'date': today,
    'generated': datetime.datetime.utcnow().isoformat() + 'Z',
    'brief': brief_text,
    'top_movers': movers[:5],
    'top_vol': top_vol[:3]
}
with open('data/polymarket-brief.json', 'w') as f:
    json.dump(output, f, indent=2)
print("Saved!")
