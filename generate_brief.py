import os, json, urllib.request, urllib.error
from datetime import date

today = str(date.today())
api_key = os.environ['GEMINI_API_KEY']

prompt = f"Generate a daily crypto market brief for {today}. Return ONLY a valid JSON object with exactly these fields, no markdown, no explanation: btc_structure, eth_flows, funding_oi, volatility_outlook, top_narratives (array of 4 strings), macro_impact, whale_flows, risk, focus, full_report"

payload = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode()
url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})

try:
    with urllib.request.urlopen(req) as r:
        data = json.loads(r.read())
except urllib.error.HTTPError as e:
    print("HTTP Error:", e.code, e.read().decode())
    raise

text = data['candidates'][0]['content']['parts'][0]['text'].strip()
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
