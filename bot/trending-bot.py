#!/usr/bin/env python3
"""
CryptoMarketz Trending Intelligence Bot
Runs Mon + Thu via GitHub Actions.
Sources: X/Nitter, Reddit (4 subs), Google Trends RSS, YouTube RSS, GitHub Trending
Claude analyses everything and writes a full intelligence report.
"""

import json, os, re, time, urllib.request, urllib.parse
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')

def fetch(url, timeout=12):
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (compatible; CryptoMarketz-Bot/1.0)',
            'Accept': 'application/rss+xml,application/xml,application/json,text/xml,*/*'
        })
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode('utf-8', errors='replace')
    except Exception as e:
        print(f"  ✗ fetch {url[:55]}: {e}")
        return None

def clean_html(s):
    return re.sub(r'<[^>]+>', '', s or '').strip()

# ─────────────────────────────────────────────
# SOURCE 1: X / TWITTER via Nitter RSS
# ─────────────────────────────────────────────
NITTER = [
    'https://nitter.privacydev.net',
    'https://nitter.poast.org',
    'https://nitter.woodland.cafe',
    'https://nitter.mint.lgbt',
]
X_QUERIES = [
    'airdrop crypto',
    'crypto airdrop 2025',
    'new crypto project launch',
    'altseason 2025',
    'crypto narrative this week',
    'defi airdrop',
    'web3 airdrop',
    'crypto trending',
]

def fetch_nitter(query, limit=5):
    enc = urllib.parse.quote(query)
    for instance in NITTER:
        xml = fetch(f"{instance}/search/rss?q={enc}&f=tweets")
        if not xml or '<item>' not in xml:
            continue
        try:
            root = ET.fromstring(xml)
            ns = {'dc': 'http://purl.org/dc/elements/1.1/'}
            posts = []
            for item in root.findall('.//item')[:limit]:
                title   = item.findtext('title','').strip()
                link    = item.findtext('link','').strip()
                desc    = clean_html(item.findtext('description',''))
                pub     = item.findtext('pubDate','').strip()
                creator = item.findtext('dc:creator','',ns).strip()
                text    = desc if len(desc) > len(title) else title
                if len(text) > 15:
                    posts.append({'text': text[:300], 'user': creator,
                                  'link': link, 'date': pub, 'query': query})
            if posts:
                print(f"  ✓ Nitter [{instance[:28]}] '{query}' → {len(posts)}")
                return posts
        except Exception as e:
            print(f"  ✗ Nitter parse: {e}")
    return []

# ─────────────────────────────────────────────
# SOURCE 2: REDDIT (4 subreddits)
# ─────────────────────────────────────────────
SUBREDDITS = [
    ('airdrops',        'top',  'week'),
    ('CryptoCurrency',  'hot',  'week'),
    ('CryptoMoonShots', 'top',  'week'),
    ('defi',            'hot',  'week'),
]

def fetch_reddit(sub, sort='hot', t='week', limit=6):
    data = fetch(f'https://www.reddit.com/r/{sub}/{sort}.json?limit=10&t={t}')
    if not data: return []
    try:
        posts = []
        for child in json.loads(data).get('data',{}).get('children',[]):
            p = child.get('data',{})
            title = p.get('title','').strip()
            score = p.get('score', 0)
            if title and score > 5:
                posts.append({
                    'title':    title,
                    'score':    score,
                    'comments': p.get('num_comments', 0),
                    'flair':    p.get('link_flair_text','') or '',
                    'url':      'https://reddit.com' + (p.get('permalink') or ''),
                    'sub':      sub,
                    'selftext': (p.get('selftext') or '')[:300]
                })
        posts.sort(key=lambda x: x['score'], reverse=True)
        print(f"  ✓ r/{sub} {sort}/{t} → {len(posts[:limit])}")
        return posts[:limit]
    except Exception as e:
        print(f"  ✗ Reddit r/{sub}: {e}")
        return []

# ─────────────────────────────────────────────
# SOURCE 3: GOOGLE TRENDS RSS
# ─────────────────────────────────────────────
TRENDS_QUERIES = [
    'cryptocurrency airdrop',
    'crypto',
    'bitcoin',
    'defi',
]

def fetch_google_trends():
    """Fetch Google Trends daily search trends RSS."""
    results = []
    # Daily trends RSS (US)
    xml = fetch('https://trends.google.com/trends/trendingsearches/daily/rss?geo=US')
    if xml:
        try:
            root = ET.fromstring(xml)
            for item in root.findall('.//item')[:15]:
                title       = item.findtext('title','').strip()
                traffic     = item.findtext('{https://trends.google.com/trends/trendingsearches/daily}approx_traffic','').strip()
                news_items  = item.findall('{https://trends.google.com/trends/trendingsearches/daily}news_item')
                news_title  = ''
                if news_items:
                    news_title = news_items[0].findtext('{https://trends.google.com/trends/trendingsearches/daily}news_item_title','').strip()
                # Only include crypto-related trends
                combined = (title + ' ' + news_title).lower()
                crypto_kws = ['crypto','bitcoin','btc','eth','coin','token','defi','nft','web3','blockchain','airdrop','solana','ethereum']
                if any(kw in combined for kw in crypto_kws):
                    results.append({
                        'term':    title,
                        'traffic': traffic,
                        'context': news_title[:120] if news_title else ''
                    })
            print(f"  ✓ Google Trends → {len(results)} crypto-related trends")
        except Exception as e:
            print(f"  ✗ Google Trends parse: {e}")

    # Also check specific search interest via RSS
    for query in TRENDS_QUERIES[:2]:
        enc = urllib.parse.quote(query)
        xml2 = fetch(f'https://trends.google.com/trends/explore/rss?q={enc}&geo=US&date=now+7-d')
        if xml2:
            try:
                root2 = ET.fromstring(xml2)
                for item in root2.findall('.//item')[:3]:
                    title = item.findtext('title','').strip()
                    if title and title not in [r['term'] for r in results]:
                        results.append({'term': title, 'traffic': '', 'context': f'Interest: {query}'})
            except:
                pass
        time.sleep(0.5)

    return results[:10]

# ─────────────────────────────────────────────
# SOURCE 4: YOUTUBE RSS (trending crypto channels)
# ─────────────────────────────────────────────
YT_CHANNELS = [
    # Channel IDs for popular crypto channels (public RSS, no API needed)
    ('UCRvqjQPSeaWn-uEx-w0XOIg', 'Coin Bureau'),
    ('UCEFJVYe4ZHpc4eUFKAPeEaA', 'Benjamin Cowen'),
    ('UCiRiQGCHGjDLT9FQXFW0I3A', 'InvestAnswers'),
    ('UCMtJYS0PrtiUwlk6zjGDEMA', 'DataDash'),
]

def fetch_youtube_rss(channel_id, channel_name):
    url = f'https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}'
    xml = fetch(url)
    if not xml: return []
    try:
        root = ET.fromstring(xml)
        ns = {
            'atom': 'http://www.w3.org/2005/Atom',
            'media': 'http://search.yahoo.com/mrss/',
            'yt': 'http://www.youtube.com/xml/schemas/2015',
        }
        videos = []
        for entry in root.findall('atom:entry', ns)[:3]:
            title     = entry.findtext('atom:title', '', ns).strip()
            link_el   = entry.find('atom:link', ns)
            link      = link_el.get('href','') if link_el is not None else ''
            published = entry.findtext('atom:published','',ns).strip()
            # Only include if crypto-related
            kws = ['airdrop','crypto','bitcoin','btc','eth','altcoin','defi','nft','bull','bear','market','token','coin','solana','ethereum','web3']
            if any(kw in title.lower() for kw in kws):
                videos.append({
                    'title':   title,
                    'channel': channel_name,
                    'link':    link,
                    'date':    published
                })
        if videos:
            print(f"  ✓ YouTube {channel_name} → {len(videos)} videos")
        return videos
    except Exception as e:
        print(f"  ✗ YouTube {channel_name}: {e}")
        return []

# ─────────────────────────────────────────────
# SOURCE 5: GITHUB TRENDING (new crypto/web3 repos)
# ─────────────────────────────────────────────
def fetch_github_trending():
    """Scrape GitHub trending for crypto/web3/blockchain repos."""
    results = []
    for topic in ['cryptocurrency', 'web3', 'defi', 'blockchain', 'airdrop']:
        html = fetch(f'https://github.com/trending?q={topic}&since=weekly')
        if not html: continue
        # Parse repo names and descriptions from HTML
        repos = re.findall(r'<h2[^>]*>\s*<a[^>]+href="(/[^"]+)"[^>]*>([\s\S]*?)</a>', html)
        descs = re.findall(r'<p[^>]*class="[^"]*col-9[^"]*"[^>]*>([\s\S]*?)</p>', html)
        stars = re.findall(r'aria-label="(\d[\d,]*) stars"', html)
        for i, (path, name) in enumerate(repos[:4]):
            name_clean = re.sub(r'\s+', ' ', name).strip()
            desc = clean_html(descs[i]) if i < len(descs) else ''
            star = stars[i].replace(',','') if i < len(stars) else '0'
            results.append({
                'repo':  name_clean,
                'desc':  desc[:150],
                'stars': int(star) if star.isdigit() else 0,
                'url':   'https://github.com' + path,
                'topic': topic
            })
        time.sleep(0.8)

    # Sort by stars
    results.sort(key=lambda x: x['stars'], reverse=True)
    print(f"  ✓ GitHub Trending → {len(results[:8])} repos")
    return results[:8]

# ─────────────────────────────────────────────
# CLAUDE ANALYSIS
# ─────────────────────────────────────────────
def analyse_with_claude(raw):
    if not ANTHROPIC_API_KEY:
        print("  ✗ No ANTHROPIC_API_KEY — skipping")
        return None

    # Build rich context string
    x_str = '\n'.join([f'- [{p["query"]}] @{p["user"]}: {p["text"][:180]}' for p in raw['x_posts'][:15]]) or 'none'

    reddit_str = ''
    for sub, posts in raw['reddit'].items():
        reddit_str += f'\nr/{sub}:\n'
        reddit_str += '\n'.join([f'  - {p["title"][:120]} (↑{p["score"]})' for p in posts[:4]])

    trends_str = '\n'.join([f'- {t["term"]} ({t["traffic"]}) — {t["context"]}' for t in raw['google_trends'][:8]]) or 'none'

    yt_str = '\n'.join([f'- [{v["channel"]}] {v["title"][:100]}' for v in raw['youtube'][:8]]) or 'none'

    gh_str = '\n'.join([f'- {r["repo"]} ⭐{r["stars"]} [{r["topic"]}]: {r["desc"][:100]}' for r in raw['github'][:6]]) or 'none'

    prompt = f"""You are a crypto market intelligence analyst. Based on this week's data from X/Twitter, Reddit, Google Trends, YouTube and GitHub, write a structured intelligence report.

DATE: {datetime.now(timezone.utc).strftime('%A %d %B %Y')}

═══ X / TWITTER (what people are posting & searching) ═══
{x_str}

═══ REDDIT ═══
{reddit_str}

═══ GOOGLE TRENDS (what people are googling this week) ═══
{trends_str}

═══ YOUTUBE (what top crypto creators are covering) ═══
{yt_str}

═══ GITHUB TRENDING (new crypto/web3 projects blowing up) ═══
{gh_str}

Based on ALL sources above, respond with ONLY this JSON (no markdown, no explanation):
{{
  "headline": "One punchy headline summarising the biggest crypto theme right now (max 12 words)",
  "summary": "2-3 sentences: what is the market narrative this week across all these sources?",
  "top_narratives": ["narrative 1", "narrative 2", "narrative 3"],
  "hot_airdrops": [
    {{"name": "project", "description": "what it is and why people are hyped, 1 sentence", "status": "upcoming/live/ended", "hype": "high/medium/low"}}
  ],
  "trending_themes": ["theme 1", "theme 2", "theme 3", "theme 4", "theme 5"],
  "github_spotlight": {{"repo": "repo name", "why": "1 sentence why this is interesting for crypto traders"}},
  "youtube_pulse": "1 sentence: what are crypto YouTubers focusing on this week?",
  "google_signal": "1 sentence: what does Google Trends tell us about retail interest right now?",
  "analyst_take": "2-3 sentences: your honest take — what should traders pay attention to and why?",
  "risk_level": "low/medium/high/extreme",
  "risk_reason": "1 sentence why"
}}"""

    try:
        body = json.dumps({
            "model": "claude-sonnet-4-6",
            "max_tokens": 1200,
            "messages": [{"role": "user", "content": prompt}]
        }).encode()
        req = urllib.request.Request(
            'https://api.anthropic.com/v1/messages',
            data=body,
            headers={
                'x-api-key':           ANTHROPIC_API_KEY,
                'anthropic-version':   '2023-06-01',
                'content-type':        'application/json'
            }
        )
        with urllib.request.urlopen(req, timeout=35) as r:
            resp = json.loads(r.read().decode())
            text = resp['content'][0]['text'].strip()
            text = re.sub(r'^```json\s*|\s*```$', '', text)
            analysis = json.loads(text)
            print(f"  ✓ Claude: \"{analysis.get('headline','')[:60]}\"")
            return analysis
    except Exception as e:
        print(f"  ✗ Claude error: {e}")
        return None

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    print(f"\n{'='*55}")
    print(f"CryptoMarketz Trending Bot — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*55}\n")

    raw = {
        'updated':      datetime.now(timezone.utc).strftime('%d %b %Y, %H:%M UTC'),
        'updated_iso':  datetime.now(timezone.utc).isoformat(),
        'x_posts':      [],
        'reddit':       {},
        'google_trends':[],
        'youtube':      [],
        'github':       [],
        'analysis':     None
    }

    # ── X / Twitter ──
    print("── X / Twitter (Nitter RSS) ──")
    seen = set()
    for query in X_QUERIES:
        for p in fetch_nitter(query, limit=5):
            if p['link'] not in seen:
                seen.add(p['link'])
                raw['x_posts'].append(p)
        time.sleep(1.2)
    print(f"   Total unique X posts: {len(raw['x_posts'])}")

    # ── Reddit ──
    print("\n── Reddit ──")
    for sub, sort, t in SUBREDDITS:
        raw['reddit'][sub] = fetch_reddit(sub, sort, t, limit=6)
        time.sleep(1)

    # ── Google Trends ──
    print("\n── Google Trends ──")
    raw['google_trends'] = fetch_google_trends()

    # ── YouTube ──
    print("\n── YouTube ──")
    for ch_id, ch_name in YT_CHANNELS:
        raw['youtube'].extend(fetch_youtube_rss(ch_id, ch_name))
        time.sleep(0.8)

    # ── GitHub ──
    print("\n── GitHub Trending ──")
    raw['github'] = fetch_github_trending()

    # ── Claude ──
    print("\n── Claude Analysis ──")
    raw['analysis'] = analyse_with_claude(raw)

    # ── Write ──
    os.makedirs('data', exist_ok=True)
    with open('data/trending.json', 'w', encoding='utf-8') as f:
        json.dump(raw, f, ensure_ascii=False, indent=2)

    size = os.path.getsize('data/trending.json')
    print(f"\n✅ data/trending.json written ({size:,} bytes)")
    print(f"   X posts:       {len(raw['x_posts'])}")
    print(f"   Reddit posts:  {sum(len(v) for v in raw['reddit'].values())}")
    print(f"   Google trends: {len(raw['google_trends'])}")
    print(f"   YouTube:       {len(raw['youtube'])}")
    print(f"   GitHub repos:  {len(raw['github'])}")
    print(f"   Claude:        {'✓' if raw['analysis'] else '✗ skipped'}")

if __name__ == '__main__':
    main()
