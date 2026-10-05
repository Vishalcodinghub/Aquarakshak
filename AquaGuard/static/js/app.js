/* AquaGuard dashboard - talks to the Python backend (/api/*). */
(() => {
'use strict';
const $ = id => document.getElementById(id);
const COL = { ph: '#8b5cf6', turb: '#d97706', tds: '#0284c7', temp: '#ef4444' };
const SC = { SAFE: '#16a34a', WARNING: '#d97706', UNSAFE: '#dc2626' };
const PAGES = { dashboard: 'Dashboard', monitoring: 'Live Monitoring', purification: 'Purification', analytics: 'Analytics',
  alerts: 'Alerts', sources: 'Water Sources', health: 'System Health', settings: 'Settings', community: 'Community Mode', learn: 'About Water Quality' };
const PM = [['ph', 'ph'], ['turb', 'turbidity'], ['tds', 'tds'], ['temp', 'temp']];
const cls = s => 'status-' + String(s || '').toLowerCase();
const esc = t => String(t).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const fv = (k, v) => v == null ? '—' : k === 'ph' ? (+v).toFixed(2) : k === 'tds' ? Math.round(v) : (+v).toFixed(1);
const D = ts => new Date(ts * 1000), hms = ts => D(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
const dt = ts => D(ts).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
const setText = (id, t) => { const e = $(id); if (e) e.textContent = t; };
const badge = (id, s) => { const e = $(id); if (e) { e.textContent = s || '—'; e.className = 'status-badge ' + (s ? cls(s) : ''); } };
const ring = (id, circ, v, color) => { const e = $(id); if (e) { e.style.strokeDasharray = (circ * Math.max(0, v) / 100) + ' ' + circ; e.style.stroke = color; } };

let S = null, page = 'dashboard', H = [], alertTab = 'active', sortKey = 'ts', sortDir = -1, pageNo = 1, range = 24, histAt = 0, online = true;

/* ---------- API / UI helpers ---------- */
async function api(path, body) {
  const r = await fetch('/api/' + path, body === undefined ? { cache: 'no-store' }
    : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  return r.json();
}
function toast(msg, type) {
  const t = document.createElement('div'); t.className = 'toast ' + (type || ''); t.textContent = msg;
  $('toasts').appendChild(t); setTimeout(() => t.remove(), 3200);
}
async function act(path, body) {
  try { const r = await api(path, body || {}); if (r.error) toast(r.error, 'bad'); else if (r.msg) toast(r.msg, 'ok'); await poll(); return r; }
  catch (e) { toast('Server not reachable', 'bad'); return {}; }
}
const ask = (title, body, ok) => new Promise(res => {
  $('modalTitle').textContent = title; $('modalBody').textContent = body; $('modalOk').textContent = ok || 'Confirm';
  $('modalBackdrop').hidden = false;
  const done = v => { $('modalBackdrop').hidden = true; res(v); };
  $('modalOk').onclick = () => done(true); $('modalCancel').onclick = () => done(false);
});

/* ---------- charts (Chart.js is vendored locally; app still works without it) ---------- */
const charts = {};
function line(id, labels, series, o) {
  o = o || {};
  const cv = $(id); if (!cv || typeof Chart === 'undefined') return;
  const mk = s => ({ label: s.l, data: s.d, yAxisID: s.y || 'y', borderColor: s.c, backgroundColor: o.bar ? s.c : s.c + '22',
    tension: .35, pointRadius: o.dots ? 3 : 0, borderWidth: o.spark ? 2 : 2, fill: !!o.fill, borderRadius: 4 });
  let c = charts[id];
  if (c) { c.data.labels = labels; series.forEach((s, i) => { if (c.data.datasets[i]) c.data.datasets[i].data = s.d; }); c.update('none'); return; }
  const sc = o.spark ? { x: { display: false }, y: { display: false } } : {
    x: { ticks: { maxTicksLimit: 6, color: '#64748b', maxRotation: 0 }, grid: { display: false } },
    y: { position: 'left', beginAtZero: !!o.zero }, };
  if (!o.spark && series.some(s => s.y === 'y1')) sc.y1 = { position: 'right', grid: { drawOnChartArea: false } };
  charts[id] = new Chart(cv, { type: o.bar ? 'bar' : 'line', data: { labels, datasets: series.map(mk) }, options: {
    responsive: true, maintainAspectRatio: false, animation: false, interaction: { mode: 'index', intersect: false },
    plugins: { legend: { display: !o.spark && series.length > 1, position: 'bottom', labels: { boxWidth: 10 } }, tooltip: { enabled: !o.spark } }, scales: sc } });
}
const multi = (id, rows, lab) => line(id, rows.map(lab || (r => hms(r.ts))), [
  { l: 'pH', d: rows.map(r => r.ph), c: COL.ph }, { l: 'Turbidity (NTU)', d: rows.map(r => r.turb), c: COL.turb },
  { l: 'Temp (°C)', d: rows.map(r => r.temp), c: COL.temp }, { l: 'TDS (ppm, right)', d: rows.map(r => r.tds), c: COL.tds, y: 'y1' }]);

/* ---------- renderers ---------- */
function rTop() {
  const r = S.reading, chip = $('statusChip');
  chip.textContent = r.status; chip.className = 'status-chip ' + cls(r.status);
  setText('scoreMiniVal', r.score); ring('scoreMiniRing', 100.5, r.score, SC[r.status]);
  $('liveDot').className = 'dot ' + (S.monitoring ? 'dot-green' : 'dot-red');
  setText('livePillText', 'Live Monitoring: ' + (S.monitoring ? 'ON' : 'OFF'));
  const n = S.alerts.filter(a => !a.resolved && a.sev !== 'INFO').length, nb = $('navAlertCount');
  nb.hidden = !n; nb.textContent = n;
}
const alertHTML = (a, btn) => `<div class="alert-item sev-${a.sev.toLowerCase()} ${a.resolved ? 'is-resolved' : ''}">
  <span>${a.sev === 'UNSAFE' ? '⛔' : a.sev === 'WARNING' ? '⚠️' : 'ℹ️'}</span>
  <div class="alert-body"><b>${a.sev === 'INFO' ? 'System event' : esc(a.sev + ' — ' + a.label)}</b><p>${esc(a.msg)}</p>
  <small class="muted">${dt(a.ts)}${a.resolved && a.rts ? ' · resolved ' + hms(a.rts) : ''}</small></div>
  ${btn && !a.resolved ? `<button class="btn btn-ghost btn-sm" data-res="${a.id}">Resolve</button>` : ''}</div>`;

function rDash() {
  const r = S.reading, s = S.settings, st = r.st;
  const h = $('heroStatus'); h.textContent = r.status; h.className = 'status-badge ' + cls(r.status);
  setText('heroReason', r.reason); setText('heroScenario', S.scenario.name); setText('heroUpdated', hms(r.ts));
  ring('scoreRingFg', 314.16, r.score, SC[r.status]); setText('scoreValue', r.score); setText('scoreCategory', r.cat);
  setText('phRange', `Acceptable: ${s.phMin} – ${s.phMax}`); setText('turbidityRange', `Warning > ${s.turbidityWarn} · Unsafe > ${s.turbidityUnsafe}`);
  setText('tdsRange', `Warning > ${s.tdsWarn} · Unsafe > ${s.tdsUnsafe}`); setText('tempRange', `Normal: ${s.tempMin} – ${s.tempMax} °C`);
  PM.forEach(([k, id]) => { setText(id + 'Value', fv(k, r[k])); badge(id + 'Badge', st[k]); line('spark-' + id, S.recent.map(x => ''), [{ l: k, d: S.recent.map(x => x[k]), c: SC[st[k]] || COL[k] }], { spark: 1 }); });
  multi('overviewChart', S.recent.slice(-20));
  const act_ = S.alerts.filter(a => !a.resolved && a.sev !== 'INFO').slice(0, 4);
  $('dashAlertList').innerHTML = act_.length ? act_.map(a => alertHTML(a, false)).join('') : '<div class="empty">✅ No active alerts</div>';
}
function rMon() {
  const r = S.reading, st = r.st;
  setText('intervalEcho', S.settings.monitoringInterval); $('miningBanner').hidden = S.scenario.key !== 'mining';
  setText('lt-ph', fv('ph', r.ph)); setText('lt-turb', fv('turb', r.turb) + ' NTU'); setText('lt-tds', fv('tds', r.tds) + ' ppm'); setText('lt-temp', fv('temp', r.temp) + ' °C');
  badge('lt-ph-b', st.ph); badge('lt-turb-b', st.turb); badge('lt-tds-b', st.tds); badge('lt-temp-b', st.temp); badge('lt-overall', r.status);
  multi('liveChart', S.recent);
}
function rPur() {
  const p = S.pur;
  $('pipeline').innerHTML = p.stages.map(s => `<div class="stage ${s.state}"><span class="stage-ico">${s.icon}</span><b>${esc(s.name)}</b><small>${esc(s.desc)}</small>
    <div class="progress"><div class="progress-bar progress-${s.state === 'done' ? 'green' : 'blue'}" style="width:${s.pct}%"></div></div></div>`).join('');
  $('purProgressBar').style.width = p.progress + '%'; setText('purProgressLabel', p.label);
  const b = p.before, a = p.after;
  badge('baBeforeStatus', p.before_status); badge('baAfterStatus', p.after_status);
  setText('baBeforePh', fv('ph', b.ph)); setText('baBeforeTurb', fv('turb', b.turb) + ' NTU'); setText('baBeforeTds', fv('tds', b.tds) + ' ppm'); setText('baBeforeTemp', fv('temp', b.temp) + ' °C');
  setText('baAfterPh', a ? fv('ph', a.ph) : '—'); setText('baAfterTurb', a ? fv('turb', a.turb) + ' NTU' : '— NTU'); setText('baAfterTds', a ? fv('tds', a.tds) + ' ppm' : '— ppm'); setText('baAfterTemp', a ? fv('temp', a.temp) + ' °C' : '— °C');
  line('beforeAfterChart', ['pH', 'Turbidity (NTU)', 'TDS (÷100)', 'Temp (°C)'], [
    { l: 'Before', d: [b.ph, b.turb, b.tds / 100, b.temp], c: '#f87171' }, { l: 'After', d: a ? [a.ph, a.turb, a.tds / 100, a.temp] : [0, 0, 0, 0], c: '#4ade80' }], { bar: 1, zero: 1 });
  $('improveBars').innerHTML = p.improve.map(i => `<div class="imp"><span>${i.label}</span><div class="progress"><div class="progress-bar progress-green" style="width:${i.pct}%"></div></div><b>${i.txt}</b></div>`).join('');
  setText('improveNote', p.note);
  setText('pumpStatus', p.pump); setText('filterStatus', p.filter); setText('disinfectionStatus', p.disinfection); setText('purSysHealth', S.health.value + '%');
  $('rawTankBar').style.width = p.tank_raw + '%'; setText('rawTankVal', p.tank_raw + '%'); $('cleanTankBar').style.width = p.tank_clean + '%'; setText('cleanTankVal', p.tank_clean + '%');
  $('modeAuto').checked = p.mode === 'auto'; $('modeManual').checked = p.mode === 'manual';
  line('treatedChart', p.trend.map(t => hms(t.ts)), [{ l: 'Before (raw) score', d: p.trend.map(t => t.before), c: '#f87171' }, { l: 'After (treated) score', d: p.trend.map(t => t.after), c: '#16a34a' }], { zero: 1 });
}
async function loadHist(force) {
  if (!force && Date.now() - histAt < 9000) return; histAt = Date.now();
  try { H = await api('history?hours=' + range); } catch (e) { return; } rAnalytics();
}
function rAnalytics() {
  const rows = H, L = [['ph', 'pH', ''], ['turb', 'Turbidity', ' NTU'], ['tds', 'TDS', ' ppm'], ['temp', 'Temperature', ' °C']];
  $('statRow').innerHTML = rows.length ? L.map(([k, n, u]) => { const v = rows.map(r => r[k]); const avg = v.reduce((a, b) => a + b, 0) / v.length;
    return `<div class="stat"><b>${n}</b><span>min <i>${fv(k, Math.min(...v))}</i></span><span>max <i>${fv(k, Math.max(...v))}</i></span><span>avg <i>${fv(k, avg)}</i></span><span>now <i>${fv(k, v[v.length - 1])}${u}</i></span></div>`; }).join('')
    : '<div class="empty">No data in this range yet.</div>';
  const stride = Math.ceil(rows.length / 150) || 1, d = rows.filter((_, i) => i % stride === 0), lab = r => range <= 24 ? hms(r.ts) : dt(r.ts);
  [['hist-ph', 'ph'], ['hist-turb', 'turb'], ['hist-tds', 'tds'], ['hist-temp', 'temp']].forEach(([id, k]) => line(id, d.map(lab), [{ l: k, d: d.map(r => r[k]), c: COL[k] }], { fill: 1 }));
  line('hist-score', d.map(lab), [{ l: 'Score', d: d.map(r => r.score), c: '#0284c7' }], { fill: 1, zero: 1 });
  rLog();
}
function rLog() {
  const q = $('logSearch').value.trim().toLowerCase(), f = $('logFilter').value, per = +$('perPage').value;
  let rows = H.filter(r => (f === 'all' || (f === 'pur-running' ? r.pur : r.status === f)));
  const txt = r => [D(r.ts).toLocaleDateString(), hms(r.ts), r.ph, r.turb, r.tds, r.temp, r.status, r.pur ? 'running' : ''].join(' ').toLowerCase();
  if (q) rows = rows.filter(r => txt(r).includes(q));
  rows = rows.slice().sort((a, b) => { const x = a[sortKey], y = b[sortKey]; return (x > y ? 1 : x < y ? -1 : 0) * sortDir; });
  const pages = Math.max(1, Math.ceil(rows.length / per)); pageNo = Math.min(pageNo, pages);
  $('logBody').innerHTML = rows.slice((pageNo - 1) * per, pageNo * per).map(r => `<tr><td>${D(r.ts).toLocaleDateString()}</td><td>${hms(r.ts)}</td><td>${fv('ph', r.ph)}</td><td>${fv('turb', r.turb)} NTU</td><td>${fv('tds', r.tds)} ppm</td><td>${fv('temp', r.temp)} °C</td><td><span class="status-badge ${cls(r.status)}">${r.status}</span></td><td>${r.pur ? '💧 Running' : '—'}</td></tr>`).join('') || '<tr><td colspan="8" class="empty">No matching entries</td></tr>';
  setText('logCount', rows.length + ' entries'); setText('pageInfo', `Page ${pageNo} / ${pages}`);
}
function rAlerts() {
  const L = S.alerts.filter(a => alertTab === 'active' ? !a.resolved && a.sev !== 'INFO' : alertTab === 'resolved' ? a.resolved && a.sev !== 'INFO' : true);
  $('alertList').innerHTML = L.length ? L.map(a => alertHTML(a, true)).join('') : `<div class="empty">${alertTab === 'active' ? '✅ No active alerts — water is within thresholds.' : 'Nothing to show here yet.'}</div>`;
}
function rSources() {
  $('mapSim').innerHTML = '<div class="map-grid" aria-hidden="true"></div>' + S.sources.map(s => `<div class="pin ${cls(s.status)}" style="left:${s.x}%;top:${s.y}%"><i></i><span>${esc(s.id)} · ${esc(s.name.split(' - ')[0])}</span></div>`).join('');
  $('sourceCards').innerHTML = S.sources.map(s => `<div class="card src-card"><h3>${esc(s.name)} <span class="status-badge ${cls(s.status)}">${s.status}</span></h3><p class="muted small">${esc(s.type)} · demo location · score ${s.score}/100</p>
    <div class="src-vals"><div><b>${fv('ph', s.ph)}</b><small>pH</small></div><div><b>${s.turb}</b><small>NTU</small></div><div><b>${s.tds}</b><small>ppm</small></div><div><b>${s.temp}</b><small>°C</small></div></div></div>`).join('');
}
function rHealth() {
  const h = S.health, col = h.value >= 80 ? SC.SAFE : h.value >= 50 ? SC.WARNING : SC.UNSAFE;
  ring('healthRing', 314.16, h.value, col); setText('healthValue', h.value);
  $('healthLegend').innerHTML = `<div><b style="color:${col}">${h.value >= 80 ? 'Healthy' : h.value >= 50 ? 'Needs attention' : 'Critical'}</b></div><div class="muted">≥ 80 healthy · 50–79 attention · &lt; 50 critical</div>`;
  $('healthTiles').innerHTML = h.tiles.map(t => `<div class="sys-tile tile-${t.ok}"><span>${t.label}</span><b>${esc(t.value)}</b></div>`).join('');
}
function fillSettings() {
  Object.entries(S.settings).forEach(([k, v]) => { const e = $('set-' + k); if (e) e.value = v; });
}
function rCommunity() {
  const r = S.reading, p = S.pur, w = { SAFE: ['✅', 'All readings look normal.', 'Water can be used after normal household handling. Keep checking this screen.', 'Good'],
    WARNING: ['⚠️', r.reason, 'Do not drink this water directly. Run the purification machine, then boil the water before drinking.', 'Check'],
    UNSAFE: ['⛔', r.reason, 'Do NOT drink or cook with this water. Use another safe source and ask a health worker to test the water.', 'Bad'] }[r.status];
  const big = $('cStatusBig'); big.className = 'status-badge c-big ' + cls(r.status); big.textContent = `${w[0]} Water Condition: ${r.status}`;
  setText('cReason', w[1]); setText('cAction', w[2]);
  [['ph', 'c-ph', 'cPh', 'cPhS', ''], ['turb', 'c-turb', 'cTurb', 'cTurbS', ' NTU'], ['tds', 'c-tds', 'cTds', 'cTdsS', ' ppm'], ['temp', 'c-temp', 'cTemp', 'cTempS', ' °C']].forEach(([k, card, v, s, u]) => {
    $(card).className = 'card c-param s-' + r.st[k].toLowerCase(); setText(v, fv(k, r[k]) + u); setText(s, { SAFE: '✅ Good', WARNING: '⚠️ Check', UNSAFE: '⛔ Bad' }[r.st[k]]); });
  setText('cPurState', p.emergency ? 'Stopped (emergency)' : p.running ? 'Cleaning water…' : p.done ? 'Water cleaned ✔' : p.progress ? 'Paused' : 'Idle');
  $('cPurBar').style.width = p.progress + '%'; setText('cPurHint', p.hint);
}
function render() {
  if (!S) return; rTop();
  ({ dashboard: rDash, monitoring: rMon, purification: rPur, alerts: rAlerts, sources: rSources, health: rHealth, community: rCommunity,
     analytics: () => loadHist(false), settings: () => {}, learn: () => {} })[page]();
}

/* ---------- navigation ---------- */
function show(p) {
  if (!PAGES[p]) p = 'dashboard'; page = p; location.hash = p;
  document.querySelectorAll('.page').forEach(e => e.classList.toggle('active', e.id === 'page-' + p));
  document.querySelectorAll('.nav-item').forEach(e => e.classList.toggle('active', e.dataset.page === p));
  setText('pageTitle', PAGES[p]); $('sidebar').classList.remove('open'); $('sidebarBackdrop').classList.remove('show'); window.scrollTo(0, 0);
  if (p === 'analytics') loadHist(true); if (p === 'settings' && S) fillSettings(); render();
}
document.querySelectorAll('[data-page]').forEach(e => e.addEventListener('click', () => show(e.dataset.page)));
$('hamburger').onclick = () => { $('sidebar').classList.toggle('open'); $('sidebarBackdrop').classList.toggle('show'); };
$('sidebarBackdrop').onclick = () => { $('sidebar').classList.remove('open'); $('sidebarBackdrop').classList.remove('show'); };

/* ---------- actions ---------- */
const on = (id, fn) => $(id).addEventListener('click', fn);
on('btnStartMon', () => act('monitoring', { on: true })); on('btnStopMon', () => act('monitoring', { on: false }));
on('btnReset', async () => { if (await ask('Reset session?', 'Clears alerts, restores the Safe Water scenario and resets the purification pipeline. History is kept.', 'Reset')) { await act('reset'); loadHist(true); } });
on('btnSafe', () => act('simulate', { scenario: 'safe' })); on('btnPolluted', () => act('simulate', { scenario: 'polluted' })); on('btnMining', () => act('simulate', { scenario: 'mining' }));
['btnStartPur', 'btnCtlStart'].forEach(i => on(i, () => act('purification', { cmd: 'start' })));
['btnStopPur', 'btnCtlStop'].forEach(i => on(i, () => act('purification', { cmd: 'stop' })));
on('btnResetPur', () => act('purification', { cmd: 'reset' }));
on('btnEmergency', async () => { if (await ask('Emergency shutdown?', 'This immediately stops the pump and the whole purification pipeline.', 'Shut down')) act('purification', { cmd: 'emergency' }); });
['modeAuto', 'modeManual'].forEach(i => $(i).addEventListener('change', e => act('purification', { cmd: 'mode', mode: e.target.value })));
$('alertSeg').addEventListener('click', e => { const b = e.target.closest('button'); if (!b) return; alertTab = b.dataset.tab; document.querySelectorAll('#alertSeg button').forEach(x => x.classList.toggle('active', x === b)); render(); });
$('alertList').addEventListener('click', e => { const b = e.target.closest('[data-res]'); if (b) act('alerts', { action: 'resolve', id: +b.dataset.res }); });
on('btnResolveAll', () => act('alerts', { action: 'resolve_all' }));
$('rangeSeg').addEventListener('click', e => { const b = e.target.closest('button'); if (!b) return; range = +b.dataset.range; pageNo = 1; document.querySelectorAll('#rangeSeg button').forEach(x => x.classList.toggle('active', x === b)); loadHist(true); });
['logSearch', 'logFilter', 'perPage'].forEach(i => $(i).addEventListener('input', () => { pageNo = 1; rLog(); }));
document.querySelectorAll('#logTable th').forEach(th => th.addEventListener('click', () => { const k = th.dataset.sort; sortDir = sortKey === k ? -sortDir : -1; sortKey = k; rLog(); }));
on('prevPage', () => { pageNo = Math.max(1, pageNo - 1); rLog(); }); on('nextPage', () => { pageNo++; rLog(); });
on('btnExportCsv', () => { location.href = '/api/export.csv'; });
on('btnSaveSettings', async () => {
  const d = {}; Object.keys(S.settings).forEach(k => { const e = $('set-' + k); if (e) d[k] = e.value; });
  const r = await act('settings', d); if (!r.error) fillSettings();
});
on('btnResetSettings', async () => { await act('settings', { reset: true }); fillSettings(); });
on('btnSeedHistory', async () => { await act('seed'); loadHist(true); });
on('btnWipeData', async () => { if (await ask('Clear all data?', 'Deletes stored history, alerts and settings (restored to defaults).', 'Clear')) { await act('wipe'); fillSettings(); loadHist(true); } });
on('btnPingGateway', async () => { const t = performance.now(), j = await api('health'); const o = $('pingResult'); o.hidden = false; o.textContent = JSON.stringify(j, null, 2) + '\nlatency: ' + Math.round(performance.now() - t) + ' ms'; });

/* ---------- polling ---------- */
let busy = false;
async function poll() {
  if (busy) return; busy = true;
  try {
    S = await api('state');
    if (!online) { online = true; toast('Reconnected to server', 'ok'); }
    $('sidebar').querySelector('.sidebar-footer').innerHTML = '<span class="dot dot-green"></span> Simulated sensors · Python backend';
    render(); if (page === 'analytics') loadHist(false);
  } catch (e) {
    online = false; $('sidebar').querySelector('.sidebar-footer').innerHTML = '<span class="dot dot-red"></span> Server offline — restart run.py';
  } finally { busy = false; }
}
(async () => { await poll(); if (S) fillSettings(); show((location.hash || '#dashboard').slice(1)); setInterval(poll, 1000); })();
})();
