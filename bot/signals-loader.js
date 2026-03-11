// ═══════════════════════════════════════════════════════════════
// VOEG DIT TOE AAN JOUW BESTAANDE <script> BLOK IN INDEX.HTML
// Laadt data/signals.json en toont de signalen op de signals pagina
// en dashboard — vervangt de huidige localStorage-only aanpak
// ═══════════════════════════════════════════════════════════════

// ── Laad bot-signalen van signals.json + combineer met handmatige signalen ──
async function loadBotSignals() {
  try {
    const res = await fetch('/data/signals.json?t=' + Date.now());
    if (!res.ok) return [];
    const data = await res.json();
    if (!Array.isArray(data)) return [];

    // Zet naar hetzelfde formaat als de bestaande handmatige signalen
    return data.map((s) => ({
      id: s.id || Date.now(),
      coin: s.coin || '—',
      type: s.type || 'WATCH',
      entry: s.entry || '',
      tp: s.tp || '',
      sl: s.sl || '',
      note: s.note || '',
      // timestamp in milliseconds voor tMs() compatibiliteit
      ts: s.timestamp ? new Date(s.timestamp).getTime() : Date.now(),
      bot: true, // markeer als bot-signaal
    }));
  } catch (e) {
    console.warn('Kon signals.json niet laden:', e.message);
    return [];
  }
}

// ── Overschrijf de bestaande renderSignals() met een versie die ook bot-signalen toont ──
async function renderSignals() {
  const manualSigs = gSigs(); // bestaande handmatige signalen uit localStorage
  const botSigs = await loadBotSignals();

  // Combineer: handmatige bovenaan, dan bot-signalen
  // Dedupliceer op coin+type combo van de laatste 60 min (voorkom dubbele bot-runs)
  const seen = new Set();
  const combined = [];

  manualSigs.forEach((s) => {
    combined.push(s);
    seen.add(s.coin + '_' + s.type);
  });

  botSigs.forEach((s) => {
    const key = s.coin + '_' + s.type;
    // Voeg bot-signaal alleen toe als er geen identiek handmatig signaal is
    if (!seen.has(key)) combined.push(s);
  });

  // Sorteer op meest recent
  combined.sort((a, b) => (b.id || b.ts || 0) - (a.id || a.ts || 0));

  const empty = '<div style="font-family:\'Orbitron\',monospace;font-size:9px;color:var(--sub)">No signals yet.</div>';

  // ── Signals full pagina ──
  const sf = document.getElementById('sig-full');
  if (sf) {
    if (!combined.length) {
      sf.innerHTML = empty;
    } else {
      sf.innerHTML = combined
        .map((s) => sigHtmlExtended(s, true))
        .join('');
    }
  }

  // ── Dashboard: toon max 3 meest recente ──
  const ds = document.getElementById('dash-signals');
  if (ds) {
    if (!combined.length) {
      ds.innerHTML = empty;
    } else {
      ds.innerHTML = combined
        .slice(0, 3)
        .map((s) => sigHtmlExtended(s, false))
        .join('');
    }
  }
}

// ── Uitgebreide versie van sigHtml() met bot-badge ──
function sigHtmlExtended(s, allowDelete) {
  const cl = s.type === 'BUY' || s.type === 'WATCH' ? 'buy' : s.type === 'SELL' ? 'sell' : 'news';
  const sub = [
    s.entry && 'Entry: ' + s.entry,
    s.tp && 'TP: ' + s.tp,
    s.sl && 'SL: ' + s.sl,
  ]
    .filter(Boolean)
    .join(' · ');

  const del =
    allowDelete && isAdm() && !s.bot
      ? `<button style="background:none;border:none;color:rgba(244,63,94,.3);cursor:pointer;font-size:14px;float:right;padding:0 3px" onclick="delSig(${s.id})">×</button>`
      : '';

  const botBadge = s.bot
    ? `<span style="font-family:'Orbitron',monospace;font-size:6px;padding:1px 5px;border-radius:2px;background:rgba(62,163,255,.15);color:#3ea3ff;border:1px solid rgba(62,163,255,.25);margin-left:4px;letter-spacing:.06em">BOT</span>`
    : '';

  const colorMap = { buy: { bg: 'rgba(74,222,128,.1)', col: 'var(--grn)' }, sell: { bg: 'rgba(244,63,94,.1)', col: 'var(--red)' }, news: { bg: 'rgba(212,175,55,.1)', col: 'var(--accent)' } };
  const c = colorMap[cl];

  const ts = s.id || s.ts || Date.now();

  return `<div style="padding:8px 0;border-bottom:1px solid rgba(212,175,55,.05);display:flex;gap:8px;align-items:flex-start">
    <div style="width:27px;height:27px;border-radius:7px;display:flex;align-items:center;justify-content:center;flex-shrink:0;background:${c.bg};color:${c.col};font-family:'Orbitron',monospace;font-size:8px;font-weight:700">${s.type.slice(0,1)}</div>
    <div style="flex:1">
      ${del}
      <div style="font-size:11px;font-weight:600;margin-bottom:1px">${escapeHtml(s.coin)}${s.type !== 'NEWS' ? ' — ' + s.type : ''}${botBadge}</div>
      ${sub ? `<div style="font-size:10px;color:var(--sub);line-height:1.4">${escapeHtml(sub)}</div>` : ''}
      ${s.note ? `<div style="font-size:10px;color:var(--sub);line-height:1.4;font-style:italic;margin-top:2px">${escapeHtml(s.note)}</div>` : ''}
      <span style="font-family:'Orbitron',monospace;font-size:8px;padding:1px 6px;border-radius:100px;font-weight:700;margin-top:2px;display:inline-block;background:${c.bg};color:${c.col}">${s.type}</span>
      <div style="font-family:'Orbitron',monospace;font-size:7.5px;color:rgba(122,106,82,.4);margin-top:2px">${tMs(ts)}</div>
    </div>
  </div>`;
}

// ── Auto-refresh elke 5 minuten ──
setInterval(renderSignals, 5 * 60 * 1000);
