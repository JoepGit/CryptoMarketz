#!/usr/bin/env python3
"""
CryptoMarketz Social Intelligence Bot
Sources: X/Twitter (Nitter RSS) + Reddit + YouTube
Runs Mon + Thu via GitHub Actions. Claude analyses everything.
"""

import json, os, re, time, urllib.request, urllib.parse
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')

def fetch(url, timeout=12):
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 CryptoMarketz-Bot/1.0',
            'Accept': 'application/rss+xml,application/xml,application/json,text/xml,*/*'
        })
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode('utf-8', errors='replace')
    except Exception as e:
        print(f"  fetch error {url[:55]}: {e}")
        return None

def clean_html(s):
    return re.sub(r'<[^>]+>', '', s or '').strip()

# ─────────────────────────────────────────────
# 1. X / TWITTER via Nitter RSS
# ─────────────────────────────────────────────
NITTER = [
    'https://nitter.privacydev.net',
    'https://nitter.poast.org',
    'https://nitter.woodland.cafe',
    'https://nitter.mint.lgbt',
    'https://nitter.cz',
]
X_QUERIES = [
    'airdrop crypto 2026',
    'new crypto project launch',
    'altseason crypto',
    'defi airdrop claim',
    'crypto narrative 2026',
]

def fetch_x(query, limit=5):
    encoded = urllib.parse.quote(query)
    for instance in NITTER:
        xml = fetch(f"{instance}/search/rss?q={encoded}&f=tweets")
        if not xml or '<item>' not in xml:
            continue
        try:
            root = ET.fromstring(xml)
            ns = {'dc': 'http://purl.org/dc/elements/1.1/'}
            posts = []
            for item in root.findall('.//item')[:limit]:
                title   = clean_html(item.findtext('title') or '')
                link    = (item.findtext('link') or '').strip()
                desc    = clean_html(item.findtext('description') or '')
                pub     = (item.findtext('pubDate') or '').strip()
                creator = (item.findtext('dc:creator', '', ns) or '').strip()
                text    = desc if len(desc) > len(title) else title
                if len(text) > 20 and link:
                    posts.append({'text': text[:280], 'user': creator, 'link': link, 'date': pub, 'query': query})
            if posts:
                print(f"  ✓ X '{query[:25]}' → {len(posts)} posts via {instance[:28]}")
                return posts[:limit]
        except Exception as e:
            print(f"  X parse error: {e}")
    print(f"  ✗ X '{query[:25]}' → all instances down")
    return []

# ─────────────────────────────────────────────
# 2. REDDIT
# ─────────────────────────────────────────────
SUBREDDITS = [
    ('airdrops',        'top',  'week'),
    ('CryptoCurrency',  'hot',  'week'),
    ('CryptoMoonShots', 'top',  'week'),
]

def fetch_reddit(sub, sort='hot', t='week', limit=7):
    data = fetch(f'https://www.reddit.com/r/{sub}/{sort}.json?limit={limit+3}&t={t}')
    if not data:
        return []
    try:
        posts = []
        for child in json.loads(data).get('data', {}).get('children', []):
            p = child.get('data', {})
            title = (p.get('title') or '').strip()
            score = p.get('score', 0)
            if title and score > 3:
                posts.append({
                    'title':    title,
                    'score':    score,
                    'comments': p.get('num_comments', 0),
                    'flair':    p.get('link_flair_text') or '',
                    'url':      'https://reddit.com' + (p.get('permalink') or ''),
                    'sub':      sub,
                })
        print(f"  ✓ r/{sub} → {len(posts)} posts")
        return posts[:limit]
    except Exception as e:
        print(f"  Reddit r/{sub} error: {e}")
        return []

# ─────────────────────────────────────────────
# 3. YOUTUBE via RSS (no API key needed)
# ─────────────────────────────────────────────
YT_CHANNELS = [
    ('Coin Bureau',    'UCqK_GSMbpiV8spgD3ZGloSw'),
    ('Benjamin Cowen', 'UCRvqjQPSeaWn-uEx-w0XOIg'),
    ('Altcoin Daily',  'UCbLhGKVY-bJPcawebgtNfbw'),
    ('DataDash',       'UCCatR7nWbYrkVXdxXb4cGXtA'),
]

def fetch_youtube(channel_name, channel_id, limit=3):
    xml = fetch(f'https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}')
    if not xml:
        return []
    try:
        root = ET.fromstring(xml)
        ns = {
            'atom':  'http://www.w3.org/2005/Atom',
            'media': 'http://search.yahoo.com/mrss/',
        }
        videos = []
        for entry in root.findall('atom:entry', ns)[:limit]:
            title   = (entry.findtext('atom:title', '', ns) or '').strip()
            link_el = entry.find('atom:link', ns)
            link    = link_el.attrib.get('href', '') if link_el is not None else ''
            pub     = (entry.findtext('atom:published', '', ns) or '').strip()
            if title and link:
                videos.append({'title': title, 'channel': channel_name, 'link': link, 'date': pub})
        print(f"  ✓ YouTube {channel_name} → {len(videos)} videos")
        return videos
    except Exception as e:
        print(f"  YouTube error {channel_name}: {e}")
        return []

# ─────────────────────────────────────────────
# 4. CLAUDE ANALYSIS
# ─────────────────────────────────────────────
def claude_analyse(data):
    if not ANTHROPIC_API_KEY:
        print("  No API key — skipping Claude")
        return None

    x_str = '\n'.join([f"- [{p['query']}] @{p.get('user','?')}: {p['text'][:140]}"
                        for p in data.get('x_posts', [])[:12]]) or 'No X posts available (Nitter instances may be down).'

    reddit_str = ''
    for sub, posts in data.get('reddit', {}).items():
        if posts:
            reddit_str += f"\nr/{sub}:\n"
            reddit_str += '\n'.join([f"  - {p['title'][:100]} (↑{p['score']})" for p in posts[:4]])
    if not reddit_str:
        reddit_str = 'No Reddit posts available.'

    yt_str = '\n'.join([f"- [{v['channel']}] {v['title']}" for v in data.get('youtube', [])[:8]]) or 'No YouTube videos.'

    prompt = f"""You are a senior crypto market analyst specialising in social sentiment and airdrop hunting.
Today is {datetime.now(timezone.utc).strftime('%A %d %B %Y')}.

Analyse the social media data below and write a structured weekly intelligence report.

═══ X / TWITTER ═══
{x_str}

═══ REDDIT ═══
{reddit_str}

═══ YOUTUBE — LATEST VIDEOS ═══
{yt_str}

Respond ONLY with a valid JSON object (no markdown, no code fences):
{{
  "headline": "One punchy headline capturing this week's biggest crypto social trend (max 12 words)",
  "summary": "2-3 sentences: what is the market talking about this week based on the data above",
  "top_narratives": ["narrative 1", "narrative 2", "narrative 3"],
  "hot_airdrops": [
    {{"name": "project name", "description": "1-2 sentences what it is and why people are excited", "status": "upcoming/live/ended", "hype": "high/medium/low", "source": "X/Reddit/YouTube"}}
  ],
  "trending_themes": ["theme 1", "theme 2", "theme 3", "theme 4", "theme 5"],
  "youtube_takeaway": "1-2 sentences: what are YouTube crypto channels saying this week?",
  "analyst_take": "2-3 sentences: honest analyst take — what to watch, what to be careful of",
  "sentiment": "bullish/neutral/bearish",
  "sentiment_reason": "1 sentence explaining the overall social sentiment"
}}"""

    try:
        body = json.dumps({
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 1200,
            "messages": [{"role": "user", "content": prompt}]
        }).encode('utf-8')
        req = urllib.request.Request(
            'https://api.anthropic.com/v1/messages',
            data=body,
            headers={
                'x-api-key': ANTHROPIC_API_KEY,
                'anthropic-version': '2023-06-01',
                'content-type': 'application/json'
            }
        )
        with urllib.request.urlopen(req, timeout=45) as r:
            resp = json.loads(r.read().decode('utf-8'))
            text = resp['content'][0]['text'].strip()
            text = re.sub(r'^```json\s*', '', text)
            text = re.sub(r'\s*```$', '', text)
            result = json.loads(text)
            print(f"  ✓ Claude: \"{result.get('headline','')[:55]}\"")
            return result
    except Exception as e:
        print(f"  Claude error: {e}")
        return None

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    print(f"\n{'='*55}")
    print(f"CryptoMarketz Trending Bot — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*55}\n")

    data = {
        'updated':      datetime.now(timezone.utc).strftime('%d %b %Y, %H:%M UTC'),
        'updated_iso':  datetime.now(timezone.utc).isoformat(),
        'x_posts':      [],
        'reddit':       {},
        'youtube':      [],
        'analysis':     None,
    }

    print("── X / Twitter (Nitter RSS) ──")
    seen = set()
    for query in X_QUERIES:
        for post in fetch_x(query, limit=5):
            if post['link'] not in seen:
                seen.add(post['link'])
                data['x_posts'].append(post)
        time.sleep(1.5)
    print(f"  Total unique X posts: {len(data['x_posts'])}")

    print("\n── Reddit ──")
    for sub, sort, t in SUBREDDITS:
        data['reddit'][sub] = fetch_reddit(sub, sort, t)
        time.sleep(1)

    print("\n── YouTube ──")
    for name, cid in YT_CHANNELS:
        data['youtube'].extend(fetch_youtube(name, cid, limit=3))
        time.sleep(0.8)

    print("\n── Claude Analysis ──")
    data['analysis'] = claude_analyse(data)

    os.makedirs('data', exist_ok=True)
    with open('data/trending.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n✅ data/trending.json written")
    print(f"   X posts:    {len(data['x_posts'])}")
    for sub, posts in data['reddit'].items():
        print(f"   r/{sub}: {len(posts)}")
    print(f"   YouTube:    {len(data['youtube'])} videos")
    print(f"   Claude:     {'✓' if data['analysis'] else '✗ skipped'}")

if __name__ == '__main__':
    main()
