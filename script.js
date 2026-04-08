'use strict';

let systemState   = 'stopped';   
let threatActive  = false;
let sidebarOpen   = true;
let uptimeStart   = null;
let uptimeTick    = null;
let alertFilter   = 'all';
let alertsData    = [];           
let membersData   = [];          
let contactsData  = [];           
let statusPollInterval  = null;
let alertPollInterval   = null;
let prevRiskScore = 0;
let camerasData   = [];         
let modalCamType  = 'ip';

function getUsers()       { return JSON.parse(localStorage.getItem('edgeai_users') || '[]'); }
function saveUsers(u)     { localStorage.setItem('edgeai_users', JSON.stringify(u)); }
function setSession(u)    { sessionStorage.setItem('edgeai_session', JSON.stringify(u)); }
function getSession()     { return JSON.parse(sessionStorage.getItem('edgeai_session') || 'null'); }
function clearSession()   { sessionStorage.removeItem('edgeai_session'); }

function showAuthError(formId, msg) {
  const e = document.getElementById(formId + '-error');
  const m = document.getElementById(formId + '-error-msg');
  const s = document.getElementById(formId + '-success');
  if (s) s.style.display = 'none';
  if (m) m.textContent = msg;
  if (e) e.style.display = 'flex';
}
function clearAuthMessages() {
  ['login-error','signup-error','signup-success'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.style.display = 'none';
  });
}
function showForm(id) {
  clearAuthMessages();
  document.querySelectorAll('.auth-form').forEach(f => f.classList.remove('active'));
  document.getElementById(id).classList.add('active');
}

function doSignup() {
  clearAuthMessages();
  const fullName = document.getElementById('s-fullname').value.trim();
  const username = document.getElementById('s-username').value.trim();
  const password = document.getElementById('s-password').value;
  const confirm  = document.getElementById('s-confirm').value;
  if (!fullName || !username || !password) { showAuthError('signup','All fields required.'); return; }
  if (username.length < 3)                { showAuthError('signup','Operator ID needs 3+ chars.'); return; }
  if (password.length < 4)               { showAuthError('signup','Password needs 4+ chars.'); return; }
  if (password !== confirm)              { showAuthError('signup','Passwords do not match.'); return; }
  const users = getUsers();
  if (users.find(u => u.username.toLowerCase() === username.toLowerCase())) {
    showAuthError('signup','Operator ID already exists.'); return;
  }
  users.push({ username, password, fullName });
  saveUsers(users);
  document.getElementById('signup-success').style.display = 'flex';
  ['s-fullname','s-username','s-password','s-confirm'].forEach(id => {
    document.getElementById(id).value = '';
  });
  setTimeout(() => showForm('frm-login'), 1800);
}

function doLogin() {
  clearAuthMessages();
  const username = document.getElementById('l-username').value.trim();
  const password = document.getElementById('l-password').value;
  if (!username || !password) { showAuthError('login','Enter Operator ID and password.'); return; }
  const users = getUsers();
  const user  = users.find(u =>
    u.username.toLowerCase() === username.toLowerCase() && u.password === password
  );
  if (!user) { showAuthError('login','Invalid Operator ID or password.'); return; }
  setSession(user);
  launchApp(user);
}

function launchApp(user) {
  const auth = document.getElementById('auth-screen');
  const app  = document.getElementById('app');
  const initials = user.fullName.split(' ').map(w => w[0]).join('').toUpperCase().slice(0,2);
  const sbAv   = document.getElementById('sb-av-initials');
  const sbName = document.getElementById('sb-username-display');
  const tbAv   = document.getElementById('tb-av-initials');
  if (sbAv)   sbAv.textContent   = initials;
  if (sbName) sbName.textContent = user.fullName;
  if (tbAv)   tbAv.textContent   = initials;
  auth.style.transition = 'opacity .4s ease';
  auth.style.opacity    = '0';
  setTimeout(() => {
    auth.style.display = 'none';
    app.style.display  = 'flex';
    app.style.opacity  = '0';
    app.style.transition = 'opacity .5s ease';
    setTimeout(() => { app.style.opacity = '1'; }, 30);
    initApp();
  }, 400);
}

function doLogout() {
  clearInterval(statusPollInterval);
  clearInterval(alertPollInterval);
  clearInterval(uptimeTick);
  clearSession();
  const app  = document.getElementById('app');
  const auth = document.getElementById('auth-screen');
  app.style.opacity = '0';
  setTimeout(() => {
    app.style.display  = 'none';
    auth.style.display = 'flex';
    auth.style.opacity = '1';
    showForm('frm-login');
    document.getElementById('l-username').value = '';
    document.getElementById('l-password').value = '';
  }, 300);
}

window.addEventListener('DOMContentLoaded', () => {
  const session = getSession();
  if (session) launchApp(session);
});

function initApp() {
  renderMembers();
  renderContacts();
  buildCamerasPage();
  startUptimeClock();
  startRealtimeClock();
  startTimestampTick('d');
  pushBrowserLocation();

 
  pollStatus();
  loadAlerts();
  statusPollInterval = setInterval(pollStatus,  3000);
  alertPollInterval  = setInterval(loadAlerts, 15000);
}

async function pollStatus() {
  try {
    const res  = await fetch('/api/status');
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();
    applyStatus(data);
  } catch (err) {
    setSystemStatus('danger', 'BACKEND OFFLINE', 'danger');
    updateStatusPanel(null);
  }
}

function applyStatus(data) {
  const risk      = data.risk_score || 0;         
  const riskPct   = Math.round(risk * 100);
  const isMonitor = data.monitoring;
  const camActive = data.camera_status === 'active';
  const isThreat  = isMonitor && risk >= (data.threshold || 0.5);

  if (isThreat) {
    setSystemStatus('danger', `⚠ THREAT — Risk ${riskPct}%`, 'danger');
  } else if (isMonitor) {
    setSystemStatus('safe', `MONITORING — Risk ${riskPct}%`, 'safe');
  } else {
    setSystemStatus('warn', 'MONITORING STOPPED', 'warning');
  }

 
  setText('ci-model',    data.model || '—');
  setText('ci-camera',   camActive ? 'Active' : 'Offline');
  setText('alerts-today', data.total_alerts ?? 0);

  const riskLabel = riskPct >= 70 ? 'HIGH' : riskPct >= 40 ? 'MEDIUM' : 'LOW';
  const riskColor = riskPct >= 70 ? 'var(--danger)' : riskPct >= 40 ? 'var(--warning)' : 'var(--safe)';
  setText('mc-risk-level', riskLabel);
  document.getElementById('mc-risk-level').style.color = riskColor;
  setText('mc-risk-score', riskPct);
  const bar = document.getElementById('mc-risk-bar');
  if (bar) { bar.style.width = riskPct + '%'; bar.style.background = riskColor; }

 
  const confPct = Math.round((data.threat_confidence || 0) * 100);
  setText('mc-ai-conf', confPct + '%');
  setText('mc-threat-conf', confPct + '%');
  const confBar = document.getElementById('mc-conf-bar');
  if (confBar) confBar.style.width = confPct + '%';

  ['d-rec','cp-rec'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.style.display = isMonitor ? 'flex' : 'none';
  });
  const nc = document.getElementById('d-nc');
  if (nc) nc.style.display = camActive ? 'none' : 'flex';

  ['d-start','cp-start'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.style.display = isMonitor ? 'none' : 'inline-flex';
  });
  ['d-stop','cp-stop'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.style.display = isMonitor ? 'inline-flex' : 'none';
  });

  setText('d-footer', camActive
    ? (isMonitor ? 'Live · Monitoring Active · AI Processing' : 'Live · Monitoring Stopped')
    : 'Camera offline — check connection');
  const dOv = document.getElementById('d-ov');
  if (dOv) dOv.style.display = camActive ? 'grid' : 'none';
  const dPh = document.getElementById('d-ph');
  if (dPh) dPh.style.display = camActive ? 'none' : 'flex';

  updateStatusPanel(data);

  if (isThreat && !threatActive && risk > prevRiskScore) {
    const now = new Date();
    showThreatPopup({
      loc:    'Room 1 — Backend Detected',
      cam:    'CAM-01',
      risk:   riskLabel,
      score:  riskPct + '%',
      ts:     now.toLocaleTimeString(),
      name:   data.last_message || 'Distress Gesture Detected',
      detail: `Threat confidence: ${confPct}%`,
    });

    fetchLatestAlertForPopup();
  }
  prevRiskScore = risk;

  if (isMonitor) highlightBtn('btn-start');
  else           highlightBtn('btn-pause');

  systemState = isMonitor ? 'running' : 'paused';
}

function updateStatusPanel(data) {
  if (!data) {
    setBeStatus('be-flask',   'OFFLINE',     'var(--danger)');
    setBeStatus('be-db',      '—',           'var(--t2)');
    setBeStatus('be-cam',     '—',           'var(--t2)');
    setBeStatus('be-loc',     '—',           'var(--t2)');
    setBeStatus('be-model',   '—',           'var(--t2)');
    setBeStatus('be-cooldown','—',           'var(--t2)');
    return;
  }
  setBeStatus('be-flask',    'ONLINE',                          'var(--safe)');
  setBeStatus('be-db',       data.db_status === 'connected' ? 'Connected' : 'Error', data.db_status === 'connected' ? 'var(--safe)' : 'var(--danger)');
  setBeStatus('be-cam',      data.camera_status === 'active' ? 'Active' : 'Offline', data.camera_status === 'active' ? 'var(--safe)' : 'var(--danger)');
  setBeStatus('be-loc',      data.location_status === 'live' ? 'GPS Live' : 'Fallback (Punjab)', data.location_status === 'live' ? 'var(--safe)' : 'var(--warning)');
  setBeStatus('be-model',    data.model || '—',                'var(--accent)');
  setBeStatus('be-cooldown', (data.cooldown_remaining || 0) + 's remaining', 'var(--t2)');
}

function setBeStatus(id, text, color) {
  const el = document.getElementById(id);
  if (el) { el.textContent = text; el.style.color = color; }
}

async function loadAlerts() {
  try {
    const res  = await fetch('/api/alerts?limit=50&hours=24');
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();

    alertsData = data.map(a => ({
      id:      a.id,
      time:    a.created_at ? a.created_at.split(' ')[1] || a.created_at : '—',
      loc:     a.message || '—',
      person:  'AI Detection',
      risk:    inferRisk(a.message),
      status:  'active',
      lat:     a.latitude,
      lon:     a.longitude,
      emailOk: !!a.email_sent,
      raw:     a,
    }));

    const badge = document.getElementById('alert-badge');
    if (badge) badge.textContent = alertsData.length;

    setText('notif-count', alertsData.length);
    renderAlertsPage();
    renderNotifPanel();
    updateSnapshotTimes();
    renderMiniAlerts();

  } catch (err) {
    console.warn('loadAlerts failed:', err.message);
  }
}

function inferRisk(message) {
  if (!message) return 'warning';
  const m = message.toLowerCase();
  if (m.includes('🚨') || m.includes('hands-up') || m.includes('distress')) return 'critical';
  if (m.includes('⚠') || m.includes('suspicious') || m.includes('possible')) return 'warning';
  return 'warning';
}

function updateSnapshotTimes() {
  alertsData.slice(0,4).forEach((a, i) => {
    const tEl   = document.getElementById(`snap-t${i+1}`);
    const locEl = document.getElementById(`snap-loc-${i+1}`);
    if (tEl)   tEl.textContent   = a.time || '—';
    if (locEl) locEl.textContent = a.loc.slice(0,28) + (a.loc.length > 28 ? '...' : '');
  });
}

function renderMiniAlerts() {
  const list = document.getElementById('mini-alerts-list');
  if (!list) return;
  if (alertsData.length === 0) {
    list.innerHTML = `<div class="mini-alert ok-row"><span class="ma-dot ok-dot"></span><div><strong>No alerts yet</strong><p>System monitoring...</p></div><span class="ma-chip chip-ok">CLEAR</span></div>`;
    return;
  }
  list.innerHTML = '';
  alertsData.slice(0,4).forEach(a => {
    const isCrit = a.risk === 'critical';
    const cls  = isCrit ? 'danger-row' : 'warn-row';
    const dot  = isCrit ? 'danger-dot' : 'warn-dot';
    const chip = isCrit ? 'chip-danger' : 'chip-warn';
    const lbl  = isCrit ? 'CRITICAL'   : 'WARNING';
    const div  = document.createElement('div');
    div.className = `mini-alert ${cls}`;
    div.innerHTML = `<span class="ma-dot ${dot}"></span><div><strong>${a.loc.slice(0,30)}</strong><p>${a.time}</p></div><span class="ma-chip ${chip}">${lbl}</span>`;
    list.appendChild(div);
  });
}

function renderNotifPanel() {
  const body = document.getElementById('notif-body');
  if (!body) return;
  if (alertsData.length === 0) {
    body.innerHTML = `<div class="np-item ok-row"><div class="np-ic ok-ic"><i class="fa-solid fa-shield-check"></i></div><div><strong>All Clear</strong><p>No recent alerts</p></div></div>`;
    return;
  }
  body.innerHTML = '';
  alertsData.slice(0,5).forEach(a => {
    const isCrit = a.risk === 'critical';
    const rowCls = isCrit ? 'danger-row' : 'warn-row';
    const icon   = isCrit ? 'fa-circle-exclamation' : 'fa-triangle-exclamation';
    const div    = document.createElement('div');
    div.className = `np-item ${rowCls}`;
    div.innerHTML = `<div class="np-ic"><i class="fa-solid ${icon}"></i></div><div><strong>${a.loc.slice(0,30)}</strong><p>${a.time}</p></div>`;
    body.appendChild(div);
  });
}

async function sysStart() {
  try {
    /* ── BACKEND CALL: POST /api/monitor/start ── */
    const res = await fetch('/api/monitor/start', { method: 'POST' });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    systemState = 'running';
    highlightBtn('btn-start');
    await pollStatus();
  } catch (err) {
    console.error('sysStart failed:', err.message);
    setSystemStatus('warn', 'START FAILED — Backend unreachable', 'warning');
  }
}

async function sysPause() {
  try {
    const res = await fetch('/api/monitor/stop', { method: 'POST' });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    systemState = 'paused';
    highlightBtn('btn-pause');
    await pollStatus();
  } catch (err) {
    console.error('sysPause failed:', err.message);
  }
}

async function sysStop() {
  await sysPause();
  highlightBtn('btn-stop');
  systemState = 'stopped';
}

async function testAlert() {
  try {
    const res  = await fetch('/api/test_email', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ message: 'TEST ALERT — Edge AI Safety System', record: true }),
    });
    const data = await res.json();

    showThreatPopup({
      loc:    'Room 1 — Test Alert',
      cam:    'CAM-01',
      risk:   'TEST',
      score:  '—',
      ts:     new Date().toLocaleTimeString(),
      name:   'Test Alert Triggered',
      detail: `Alert ID: ${data.alert_id || '—'}`,
    });

    const emailEl = document.getElementById('td-email-status');
    if (emailEl) {
      emailEl.innerHTML = data.ok
        ? '<i class="fa-solid fa-circle-check"></i> Delivered'
        : `<i class="fa-solid fa-circle-xmark" style="color:var(--danger)"></i> Failed (check .env SMTP)`;
    }

    if (data.alert_id) fetchLatestAlertForPopup();

    setTimeout(loadAlerts, 1500);
  } catch (err) {
    alert('Test alert failed: ' + err.message + '\nMake sure Flask is running.');
  }
}

function pushBrowserLocation() {
  if (!navigator.geolocation) return;
  navigator.geolocation.getCurrentPosition(
    pos => {
      fetch('/api/location', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({
          latitude:  pos.coords.latitude,
          longitude: pos.coords.longitude,
        }),
      }).catch(() => {});
    },
    () => {},
    { enableHighAccuracy: true, timeout: 10000 }
  );
}

function handleStreamLoad() {

  const ph = document.getElementById('d-ph');
  if (ph) ph.style.display = 'none';
}

function handleStreamError() {

  const img = document.getElementById('backend-stream');
  if (img) img.style.display = 'none';
  const ph = document.getElementById('d-ph');
  if (ph) ph.style.display = 'flex';
  setText('d-footer', 'Stream offline — start Flask: python app.py');
  setSystemStatus('danger', 'BACKEND OFFLINE', 'danger');
}

function retryStream() {

  const img = document.getElementById('backend-stream');
  if (img) {
    img.style.display = 'block';
    img.src = '/video_feed?t=' + Date.now(); 
  }
  const ph = document.getElementById('d-ph');
  if (ph) ph.style.display = 'none';
}

function showThreatPopup(info) {
  if (threatActive) return; 
  threatActive = true;
  setText('td-loc',    info.loc);
  setText('td-cam',    info.cam);
  setText('td-risk',   info.risk);
  setText('td-score',  info.score);
  setText('td-ts',     info.ts);
  setText('td-name',   info.name);
  setText('td-detail', info.detail);
  setText('tm-time',   info.ts);
  setText('td-coords', 'Fetching coordinates...');
  const emailEl = document.getElementById('td-email-status');
  if (emailEl) emailEl.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> Sending...';
  document.getElementById('threat-overlay').classList.add('open');
  setSystemToThreat(info.loc, info.cam);
}

async function fetchLatestAlertForPopup() {
  try {
    const res  = await fetch('/api/alerts?limit=1&hours=1');
    const data = await res.json();
    if (!data || data.length === 0) return;
    const a = data[0];
    const coordText = `${a.latitude?.toFixed(5)}, ${a.longitude?.toFixed(5)}`;
    setText('td-coords', coordText);
    const mapLink = document.getElementById('td-map-link');
    if (mapLink) {
      mapLink.href = `https://maps.google.com/?q=${a.latitude},${a.longitude}`;
      mapLink.textContent = 'Open in Google Maps ↗';
    }
    const emailEl = document.getElementById('td-email-status');
    if (emailEl) {
      emailEl.innerHTML = a.email_sent
        ? '<i class="fa-solid fa-circle-check"></i> Delivered'
        : (a.email_error
            ? `<i class="fa-solid fa-circle-xmark" style="color:var(--danger)"></i> Failed`
            : '<i class="fa-solid fa-circle-notch fa-spin"></i> Sending...');
    }
  } catch (_) {}
}

function setSystemToThreat(loc, cam) {
  setSystemStatus('danger', `⚠ THREAT — ${loc}`, 'danger');
  const mcMain = document.getElementById('mc-main');
  if (mcMain) mcMain.classList.add('threat-mode');
  setText('mc-status', 'THREAT');
  const mcStatus = document.getElementById('mc-status');
  if (mcStatus) mcStatus.className = 'mc-big danger-text';
  setText('mc-sub', `⚠ ${cam} · Alert sent via email`);
}

function resolveAlert() {
  document.getElementById('threat-overlay').classList.remove('open');
  threatActive = false;
  prevRiskScore = 0;
  setSystemStatus('safe', 'SAFE — Threat Resolved', 'safe');
  const mcMain = document.getElementById('mc-main');
  if (mcMain) mcMain.classList.remove('threat-mode');
  loadAlerts();
}

function closeKeep() {
  document.getElementById('threat-overlay').classList.remove('open');
  threatActive = false;
}

function renderAlertsPage() {
  const list = document.getElementById('alerts-full-list');
  if (!list) return;

  const filtered =
    alertFilter === 'all'      ? alertsData :
    alertFilter === 'critical' ? alertsData.filter(a => a.risk === 'critical') :
    alertFilter === 'warning'  ? alertsData.filter(a => a.risk === 'warning') :
                                 alertsData.filter(a => a.status === 'resolved');

  list.innerHTML = '';

  if (filtered.length === 0) {
    list.innerHTML = `<div style="text-align:center;padding:48px;color:var(--t2)">
      <i class="fa-solid fa-circle-check" style="font-size:2.5rem;color:var(--safe);display:block;margin-bottom:12px"></i>
      No alerts found for this filter.</div>`;
    return;
  }

  filtered.forEach((a, i) => {
    const isCrit = a.risk === 'critical';
    const iconCl = isCrit ? 'fa-circle-exclamation' : 'fa-triangle-exclamation';
    const bgCl   = isCrit ? 'rgba(239,68,68,0.15)' : 'rgba(245,158,11,0.15)';
    const fgCl   = isCrit ? 'var(--danger)' : 'var(--warning)';
    const riskCls = isCrit ? 'risk-critical' : 'risk-warning';

    const div = document.createElement('div');
    div.className = 'alert-row-full glass';
    div.style.animationDelay = `${i * 0.04}s`;
    div.innerHTML = `
      <div class="ar-icon" style="background:${bgCl};color:${fgCl}">
        <i class="fa-solid ${iconCl}"></i>
      </div>
      <div class="ar-body">
        <div class="ar-type">${escHtml(a.loc)}</div>
        <div class="ar-meta">
          ${a.time}
          · ${a.emailOk ? '<i class="fa-solid fa-envelope" style="color:var(--safe)"></i> Email sent' : '<i class="fa-solid fa-envelope" style="color:var(--t2)"></i> Email not sent'}
          · Lat: ${a.lat?.toFixed(4) ?? '—'}, Lon: ${a.lon?.toFixed(4) ?? '—'}
        </div>
      </div>
      <span class="risk-chip ${riskCls}">${a.risk.toUpperCase()}</span>
      <span class="status-chip status-active">Active</span>
      <div class="tbl-actions">
        <a class="tbl-btn tb-view"
           href="https://maps.google.com/?q=${a.lat},${a.lon}"
           target="_blank">Map</a>
      </div>`;
    list.appendChild(div);
  });
}

function filterAlerts(f, btn) {
  alertFilter = f;
  document.querySelectorAll('.f-btn').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  renderAlertsPage();
}

function goPage(page, el) {
  event.preventDefault();
  document.querySelectorAll('.sb-link').forEach(l => l.classList.remove('active'));
  const link = document.querySelector(`[onclick*="goPage('${page}'"]`);
  if (link) link.classList.add('active');
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  const target = document.getElementById('page-' + page);
  if (target) target.classList.add('active');
  const titles = { dashboard:'Dashboard', cameras:'Cameras', alerts:'Alerts', members:'Members', contacts:'Contacts', settings:'Settings' };
  setText('tb-page-name', titles[page] || page);
  if (window.innerWidth <= 768)
    document.getElementById('sidebar').classList.remove('mobile-open');
  /* Reload map iframe when navigating to alerts */
  if (page === 'alerts') {
    const iframe = document.getElementById('alert-map');
    if (iframe) iframe.src = '/api/map?t=' + Date.now();
  }
}
function toggleSidebar() {
  const sb = document.getElementById('sidebar');
  const mw = document.getElementById('main-wrap');
  if (window.innerWidth <= 768) {
    sb.classList.toggle('mobile-open');
  } else {
    sidebarOpen = !sidebarOpen;
    sb.classList.toggle('collapsed', !sidebarOpen);
    mw.classList.toggle('shifted', !sidebarOpen);
  }
}

function toggleNotif() {
  document.getElementById('notif-panel').classList.toggle('open');
}
document.addEventListener('click', e => {
  const np  = document.getElementById('notif-panel');
  const btn = document.querySelector('.tb-icon-btn');
  if (np && btn && !np.contains(e.target) && !btn.contains(e.target))
    np.classList.remove('open');
});

function startUptimeClock() {
  uptimeStart = Date.now();
  clearInterval(uptimeTick);
  uptimeTick = setInterval(() => {
    const e = Math.floor((Date.now() - uptimeStart) / 1000);
    const h = String(Math.floor(e / 3600)).padStart(2,'0');
    const m = String(Math.floor((e % 3600) / 60)).padStart(2,'0');
    const s = String(e % 60).padStart(2,'0');
    setText('uptime', `${h}:${m}:${s}`);
  }, 1000);
}

function startRealtimeClock() {
  const tick = () => {
    const n = new Date();
    setText('tb-clock',
      String(n.getHours()).padStart(2,'0') + ':' +
      String(n.getMinutes()).padStart(2,'0') + ':' +
      String(n.getSeconds()).padStart(2,'0'));
  };
  tick();
  setInterval(tick, 1000);
}

function startTimestampTick(prefix) {
  const tick = () => {
    const el = document.getElementById(prefix + '-ts');
    if (el) el.textContent = new Date().toLocaleTimeString('en-GB');
  };
  tick();
  setInterval(tick, 1000);
}

function setSystemStatus(ledClass, valText, textClass) {
  const colorMap = { safe:'var(--safe)', warning:'var(--warning)', danger:'var(--danger)' };
  const color = colorMap[textClass] || 'var(--t2)';

  /* Control bar */
  const led = document.getElementById('ctrl-led');
  if (led) { led.className = 'ctrl-led ' + ledClass + '-led'; }
  const val = document.getElementById('ctrl-val');
  if (val) { val.textContent = valText; val.style.color = color; }

  /* Metric card */
  const mcLed = document.getElementById('mc-led');
  if (mcLed) mcLed.className = 'mc-led ' + ledClass + '-led';

  const statusMap = {
    safe:    { txt:'SAFE',    cls:'mc-big safe-text',   sub:'No active threats detected' },
    warn:    { txt:'PAUSED',  cls:'mc-big warn-text',   sub:'Monitoring on hold' },
    danger:  { txt:'THREAT',  cls:'mc-big danger-text', sub:'⚠ Threat detected!' },
  };
  const s = statusMap[ledClass] || statusMap.safe;
  setText('mc-status', s.txt);
  const mcStatus = document.getElementById('mc-status');
  if (mcStatus) mcStatus.className = s.cls;
  setText('mc-sub', s.sub);
  const mcMain = document.getElementById('mc-main');
  if (mcMain) mcMain.classList.toggle('threat-mode', ledClass === 'danger');

  /* Sidebar dot */
  const sbDot = document.getElementById('sb-dot');
  if (sbDot) {
    sbDot.className = 'sb-dot';
    sbDot.classList.add(textClass === 'warning' ? 'warn-dot' : textClass + '-dot');
  }
  setText('sb-status-text', ledClass === 'safe' ? 'SYSTEM SAFE' : ledClass === 'warn' ? 'PAUSED' : 'THREAT ACTIVE');

  const tiDot = document.getElementById('ti-dot');
  if (tiDot) {
    tiDot.className = 'ti-dot';
    tiDot.classList.add(textClass === 'warning' ? 'warn-dot' : textClass + '-dot');
  }
  setText('ti-text', textClass === 'safe' ? 'SAFE' : textClass === 'warning' ? 'PAUSED' : 'ALERT');
}

function highlightBtn(id) {
  ['btn-start','btn-pause','btn-stop'].forEach(b => {
    const el = document.getElementById(b);
    if (el) el.style.opacity = b === id ? '1' : '0.5';
  });
}


function buildCamerasPage() {
  renderCamerasList();
}

function renderCamerasList() {
  const list  = document.getElementById('cameras-list');
  const empty = document.getElementById('cam-empty-hint');
  if (!list) return;
  list.innerHTML = '';
  if (camerasData.length === 0) {
    if (empty) empty.style.display = 'flex';
    return;
  }
  if (empty) empty.style.display = 'none';
  camerasData.forEach(cam => {
    const card = document.createElement('div');
    card.className = 'cam-list-card glass';
    card.innerHTML = `
      <div class="cam-list-hdr">
        <div class="cam-list-hdr-l">
          <i class="fa-solid fa-video"></i><span>${escHtml(cam.name)}</span>
          <span class="nc-ind"><span></span>NOT CONNECTED</span>
        </div>
        <div style="display:flex;align-items:center;gap:8px">
          <span class="ai-badge"><i class="fa-solid fa-microchip"></i> AI Active</span>
          <button class="cam-remove-btn" onclick="removeCamera('${cam.id}')">
            <i class="fa-solid fa-trash"></i> Remove
          </button>
        </div>
      </div>
      <div class="cam-ph" style="aspect-ratio:16/9;position:relative">
        <div class="cam-grid-ov"></div>
        <div class="cam-ph-cnt">
          <i class="fa-solid fa-network-wired"></i>
          <p>${cam.type === 'ip' ? cam.address : cam.address}</p>
          <span>IP/RTSP stream requires backend proxy</span>
        </div>
      </div>
      <div class="cam-footer">
        <span>${cam.type === 'ip' ? 'IP: ' : 'RTSP: '}${escHtml(cam.address)}</span>
      </div>`;
    list.appendChild(card);
  });
}

function openAddCamModal() {
  modalCamType = 'ip';
  setText('nc-name', '');
  const ip   = document.getElementById('nc-ip-row');
  const rtsp = document.getElementById('nc-rtsp-row');
  if (ip)   ip.style.display   = 'flex';
  if (rtsp) rtsp.style.display = 'none';
  document.querySelectorAll('.modal-tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.modal-tab')[0].classList.add('active');
  document.getElementById('add-cam-modal').classList.add('open');
}
function closeAddCamModal() {
  document.getElementById('add-cam-modal').classList.remove('open');
}
function modalCamTab(btn, mode) {
  modalCamType = mode;
  document.querySelectorAll('.modal-tab').forEach(t => t.classList.remove('active'));
  btn.classList.add('active');
  const ip   = document.getElementById('nc-ip-row');
  const rtsp = document.getElementById('nc-rtsp-row');
  if (ip)   ip.style.display   = mode === 'ip'   ? 'flex' : 'none';
  if (rtsp) rtsp.style.display = mode === 'cctv' ? 'flex' : 'none';
}
function addCamera() {
  const nameEl = document.getElementById('nc-name');
  const name   = nameEl.value.trim();
  if (!name) { nameEl.style.borderBottomColor = 'var(--danger)'; nameEl.focus(); return; }
  const ipVal   = document.getElementById('nc-ip-val')?.value.trim()   || '';
  const rtspVal = document.getElementById('nc-rtsp-val')?.value.trim() || '';
  const address = modalCamType === 'ip' ? ipVal : rtspVal;
  camerasData.push({ id: 'cam_' + Date.now(), name, type: modalCamType, address });
  renderCamerasList();
  closeAddCamModal();
}
function removeCamera(id) {
  camerasData = camerasData.filter(c => c.id !== id);
  renderCamerasList();
}

function renderMembers() {
  const grid = document.getElementById('member-cards');
  if (!grid) return;
  grid.innerHTML = '';
  if (membersData.length === 0) {
    grid.innerHTML = `<div class="empty-state"><i class="fa-solid fa-users"></i><p>No members registered yet</p><span>Add a member using the form</span></div>`;
    return;
  }
  membersData.forEach(m => {
    const card = document.createElement('div');
    card.className = 'member-card glass';
    const statusHtml = m.status === 'safe'
      ? `<span class="mc-status-safe"><i class="fa-solid fa-shield-check"></i> Safe</span>`
      : `<span class="mc-status-alert"><i class="fa-solid fa-triangle-exclamation"></i> Alert</span>`;
    const face = m.photo
      ? `<img src="${m.photo}" alt="${m.name}"/>`
      : `<span class="mc-initials">${m.initials}</span>`;
    card.innerHTML = `
      <div class="mc-face">${face}</div>
      <div class="mc-name">${escHtml(m.name)}</div>
      <div class="mc-role">${escHtml(m.role)}</div>
      ${statusHtml}
      <button class="mc-del-btn" onclick="deleteMember(${m.id})"><i class="fa-solid fa-trash"></i></button>`;
    grid.appendChild(card);
  });
}

function deleteMember(id) {
  membersData = membersData.filter(m => m.id !== id);
  renderMembers();
}

function previewPhoto(input) {
  if (!input.files || !input.files[0]) return;
  const reader = new FileReader();
  reader.onload = e => {
    const inner = document.getElementById('pu-inner');
    if (inner) inner.innerHTML = `<img src="${e.target.result}" style="width:80px;height:80px;border-radius:50%;object-fit:cover"/>`;
    window._pendingPhoto = e.target.result;
  };
  reader.readAsDataURL(input.files[0]);
}

function registerMember() {
  const name = document.getElementById('reg-name').value.trim();
  const role = document.getElementById('reg-role').value;
  if (!name || !role) { shakePanel('.register-panel'); return; }
  const initials = name.split(' ').map(n => n[0]).join('').toUpperCase().slice(0,2);
  membersData.unshift({ id: Date.now(), name, role, status:'safe', initials, photo: window._pendingPhoto || null });
  renderMembers();
  document.getElementById('reg-name').value = '';
  document.getElementById('reg-role').value = '';
  const pu = document.getElementById('pu-inner');
  if (pu) pu.innerHTML = `<i class="fa-solid fa-camera-retro"></i><p>Upload Face Photo</p><span>Click or drag image here</span>`;
  window._pendingPhoto = null;
  flashBtn('.btn-register','<i class="fa-solid fa-check"></i> Member Added!');
}

function renderContacts() {
  const list = document.getElementById('contacts-list');
  if (!list) return;
  list.innerHTML = '';
  if (contactsData.length === 0) {
    list.innerHTML = `<div class="empty-state"><i class="fa-solid fa-phone"></i><p>No contacts added yet</p><span>Add emergency contacts using the form</span></div>`;
    return;
  }
  contactsData.forEach(c => {
    const card = document.createElement('div');
    card.className = 'contact-card glass';
    const initials = c.name.split(' ').map(w => w[0]).join('').slice(0,2).toUpperCase();
    card.innerHTML = `
      <div class="cc-av">${initials}</div>
      <div class="cc-info">
        <strong>${escHtml(c.name)}</strong>
        <span><i class="fa-solid fa-phone" style="font-size:.7rem;margin-right:4px"></i>${escHtml(c.phone)}</span>
        <p><i class="fa-solid fa-envelope" style="font-size:.7rem;margin-right:4px"></i>${escHtml(c.email)}</p>
        <span class="cc-rel">${escHtml(c.rel)}</span>
      </div>
      <button class="cc-del" onclick="deleteContact(${c.id})"><i class="fa-solid fa-trash"></i></button>`;
    list.appendChild(card);
  });
}

function addContact() {
  const name  = document.getElementById('c-name').value.trim();
  const phone = document.getElementById('c-phone').value.trim();
  const email = document.getElementById('c-email').value.trim();
  const rel   = document.getElementById('c-rel').value;
  if (!name || !phone) { shakePanel('.register-panel'); return; }
  contactsData.push({ id: Date.now(), name, phone, email, rel: rel || 'Contact' });
  renderContacts();
  document.getElementById('c-name').value  = '';
  document.getElementById('c-phone').value = '';
  document.getElementById('c-email').value = '';
  document.getElementById('c-rel').value   = '';
  flashBtn('.btn-register','<i class="fa-solid fa-check"></i> Contact Added!');
}

function deleteContact(id) {
  contactsData = contactsData.filter(c => c.id !== id);
  renderContacts();
}

function setText(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

function escHtml(s) {
  if (!s) return '';
  return String(s)
    .replace(/&/g,'&amp;')
    .replace(/</g,'&lt;')
    .replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;');
}

function shakePanel(selector) {
  const el = document.querySelector(selector);
  if (!el) return;
  el.style.animation = 'none';
  void el.offsetWidth;
  el.style.animation = 'shake .4s ease';
}

function flashBtn(selector, html) {
  const el = document.querySelector(selector);
  if (!el) return;
  const orig = el.innerHTML;
  el.innerHTML = html;
  el.style.background = 'linear-gradient(90deg,#166534,#16a34a)';
  setTimeout(() => { el.innerHTML = orig; el.style.background = ''; }, 1800);
}

const _ks = document.createElement('style');
_ks.textContent = `
@keyframes shake{0%,100%{transform:translateX(0)}20%{transform:translateX(-8px)}40%{transform:translateX(8px)}60%{transform:translateX(-5px)}80%{transform:translateX(5px)}}
@keyframes slide-in{from{opacity:0;transform:translateX(-16px)}to{opacity:1;transform:translateX(0)}}
`;
document.head.appendChild(_ks);

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    document.getElementById('threat-overlay')?.classList.remove('open');
    document.getElementById('notif-panel')?.classList.remove('open');
    threatActive = false;
  }
  if (e.key === 'F1') { e.preventDefault(); testAlert(); }
  if (e.key === 'F2') { e.preventDefault(); sysStart(); }
  if (e.key === 'F3') { e.preventDefault(); sysPause(); }
});
