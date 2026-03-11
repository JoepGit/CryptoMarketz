import os, json, urllib.request, urllib.error
from datetime import date

today = str(date.today())
api_key = os.environ['CLAUDE_API_KEY']

prompt = f"Generate a daily crypto market brief for {today}. Return ONLY a valid JSON object with exactly these fields, no markdown, no explanation: btc_structure, eth_flows, funding_oi, volatility_outlook, top_narratives (array of 4 strings), macro_impact, whale_flows, risk, focus, full_report"

payload = json.dumps({
    "model": "claude-haiku-4-5-20251001",
    "max_tokens": 1024,
    "messages": [{"role": "user", "content": prompt}]
}).encode()

url = "https://api.anthropic.com/v1/messages"
req = urllib.request.Request(url, data=payload, headers={
    "Content-Type": "application/json",
    "x-api-key": api_key,
    "anthropic-version": "2023-06-01"
})

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

print('Brief written successfully')
