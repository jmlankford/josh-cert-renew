/* SSL Manager — single-page application
 *
 * All three views (Domains, Credentials, History) are rendered here.
 * No frontend framework. No build step. Vanilla ES2022.
 */

'use strict';

// ── State ─────────────────────────────────────────────────────────────────────────────

const state = {
  domains: [],
  cfZones: [],
  cpProfiles: [],
  history: [],
  filter: 'all',        // 'all' | 'expiring' | 'expired' | 'never'
  search: '',
  sort: { col: 'fqdn', dir: 'asc' },
  editingCfId: null,
  editingCpId: null,
  cpAuthMethod: 'api_token',
};

// ── API helpers ────────────────────────────────────────────────────────────────────

async function api(method, path, body) {
  const opts = {
    method,
    headers: { 'Content-Type': 'application/json' },
  };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const res = await fetch(path, opts);
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try { const j = await res.json(); msg = j.detail || JSON.stringify(j); } catch (_) {}
    throw new Error(msg);
  }
  if (res.status === 204) return null;
  return res.json();
}

const GET    = (p)    => api('GET',    p);
const POST   = (p, b) => api('POST',   p, b);
const PUT    = (p, b) => api('PUT',    p, b);
const DELETE = (p)    => api('DELETE', p);

// ── Date utilities ────────────────────────────────────────────────────────────────────

function expiryClass(iso) {
  if (!iso) return 'exp-never';
  const exp = new Date(iso);
  const now = new Date();
  if (exp < now) return 'exp-expired';
  const diff = (exp - now) / 86400000;
  if (diff <= 60) return 'exp-soon';
  return 'exp-ok';
}

function fmtDate(iso) {
  if (!iso) return 'NOT ISSUED';
  return new Date(iso).toISOString().slice(0, 10);
}

function fmtDatetime(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toISOString().replace('T', ' ').slice(0, 19) + ' UTC';
}

// ── Navigation ──────────────────────────────────────────────────────────────────────────

document.querySelectorAll('.nav-link').forEach(link => {
  link.addEventListener('click', () => {
    document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    link.classList.add('active');
    const viewId = link.dataset.view;
    document.getElementById(viewId).classList.add('active');
    if (viewId === 'domains-view') loadDomains();
    if (viewId === 'credentials-view') loadCredentials();
    if (viewId === 'history-view') loadHistory();
  });
});

// ── Dashboard summary ─────────────────────────────────────────────────────────────────────

async function loadDashboard() {
  try {
    const d = await GET('/api/dashboard');
    document.getElementById('stat-total-val').textContent    = d.total;
    document.getElementById('stat-expiring-val').textContent = d.expiring_soon;
    document.getElementById('stat-expired-val').textContent  = d.expired;
    document.getElementById('stat-never-val').textContent    = d.never_issued;

    const runEl = document.getElementById('stat-last-run');
    const result = d.last_run_result;
    if (result === 'NEVER RUN') {
      runEl.textContent = 'NEVER RUN';
      runEl.className = 'stat-value run-never';
    } else {
      const ts = d.last_run_timestamp ? fmtDatetime(d.last_run_timestamp) : '—';
      const cls = result === 'PASS' ? 'run-pass' : 'run-fail';
      runEl.innerHTML = `<span style="font-size:13px;color:var(--text-dim)">${ts}</span><br><span class="${cls}">${result}</span>`;
      runEl.className = 'stat-value';
    }
  } catch (e) {
    console.error('Dashboard load failed', e);
  }
}

// Click on summary stats to filter the table
document.querySelectorAll('.summary-stat[data-filter]').forEach(el => {
  el.addEventListener('click', () => {
    const f = el.dataset.filter;
    setFilter(f);
    // Switch to domains view if not already there
    document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    document.querySelector('[data-view="domains-view"]').classList.add('active');
    document.getElementById('domains-view').classList.add('active');
    loadDomains();
  });
});

// ── Domains ─────────────────────────────────────────────────────────────────────────────

async function loadDomains() {
  try {
    const [domains, cfZones, cpProfiles] = await Promise.all([
      GET('/api/domains'),
      GET('/api/credentials/cloudflare'),
      GET('/api/credentials/cpanel'),
    ]);
    state.domains    = domains;
    state.cfZones    = cfZones;
    state.cpProfiles = cpProfiles;
    renderDomainTable();
    loadDashboard();
  } catch (e) {
    console.error('Failed to load domains', e);
  }
}

function getProfileName(id) {
  const p = state.cpProfiles.find(p => p.id === id);
  return p ? p.profile_name : '—';
}

function recordTypeLabel(domain) {
  if (!domain.subdomain) return 'APEX';
  return domain.subdomain.toUpperCase();
}

function getFilteredDomains() {
  const now = new Date();
  const soon = new Date(now.getTime() + 30 * 86400000);

  return state.domains
    .filter(d => {
      const search = state.search.toLowerCase();
      if (search && !d.fqdn.toLowerCase().includes(search)) return false;

      if (state.filter === 'all') return true;
      if (state.filter === 'never') return d.status === 'NEVER ISSUED';
      if (state.filter === 'expired') {
        return d.expiry_date && new Date(d.expiry_date) < now;
      }
      if (state.filter === 'expiring') {
        return d.expiry_date && new Date(d.expiry_date) >= now && new Date(d.expiry_date) <= soon;
      }
      return true;
    })
    .sort((a, b) => {
      const col = state.sort.col;
      const dir = state.sort.dir === 'asc' ? 1 : -1;
      let va, vb;

      if (col === 'fqdn')        { va = a.fqdn; vb = b.fqdn; }
      else if (col === 'record_type') { va = recordTypeLabel(a); vb = recordTypeLabel(b); }
      else if (col === 'expiry_date') { va = a.expiry_date || ''; vb = b.expiry_date || ''; }
      else if (col === 'profile') { va = getProfileName(a.cpanel_profile_id); vb = getProfileName(b.cpanel_profile_id); }
      else if (col === 'status')  { va = a.status; vb = b.status; }
      else                        { va = ''; vb = ''; }

      return va < vb ? -dir : va > vb ? dir : 0;
    });
}

function renderDomainTable() {
  const tbody = document.getElementById('domain-tbody');
  const empty = document.getElementById('domains-empty');
  const rows = getFilteredDomains();

  if (!rows.length) {
    tbody.innerHTML = '';
    empty.classList.remove('hidden');
    return;
  }
  empty.classList.add('hidden');

  tbody.innerHTML = rows.map((d, idx) => {
    const ec   = expiryClass(d.expiry_date);
    const exp  = d.expiry_date ? fmtDate(d.expiry_date) : 'NOT ISSUED';
    const sc   = 'status-' + d.status.replace(/\s/g, '-');
    const prof = getProfileName(d.cpanel_profile_id);
    const rec  = recordTypeLabel(d);
    const wildcard = d.is_wildcard ? ' <span title="Wildcard cert" style="color:var(--accent);font-size:10px">★</span>' : '';

    const issueBtn  = (d.status === 'NEVER ISSUED' || d.status === 'ERROR')
      ? `<button class="action-btn btn-issue" data-action="issue" data-id="${d.id}" data-fqdn="${d.fqdn}">Issue</button>`
      : '';
    const renewBtn  = d.expiry_date || d.status === 'ACTIVE'
      ? `<button class="action-btn btn-renew" data-action="renew" data-id="${d.id}" data-fqdn="${d.fqdn}">Renew</button>`
      : '';
    const deleteBtn = `<button class="action-btn btn-delete" data-action="delete" data-id="${d.id}" data-fqdn="${d.fqdn}">Delete</button>`;

    const delay = `animation-delay:${idx * 35}ms`;

    return `<tr style="${delay}">
      <td class="td-domain">${escHtml(d.fqdn)}${wildcard}</td>
      <td class="td-record">${escHtml(rec)}</td>
      <td class="td-expiry ${ec}">${escHtml(exp)}</td>
      <td>${escHtml(prof)}</td>
      <td><span class="status-badge ${sc}">${escHtml(d.status)}</span></td>
      <td>${issueBtn}${renewBtn}${deleteBtn}</td>
    </tr>`;
  }).join('');
}

// Table column sort
document.querySelectorAll('#domain-table thead th[data-col]').forEach(th => {
  th.addEventListener('click', () => {
    const col = th.dataset.col;
    if (state.sort.col === col) {
      state.sort.dir = state.sort.dir === 'asc' ? 'desc' : 'asc';
    } else {
      state.sort.col = col;
      state.sort.dir = 'asc';
    }
    document.querySelectorAll('#domain-table thead th').forEach(h => h.classList.remove('sorted'));
    th.classList.add('sorted');
    th.querySelector('.sort-arrow').textContent = state.sort.dir === 'asc' ? '↑' : '↓';
    renderDomainTable();
  });
});

// Filter buttons
function setFilter(f) {
  state.filter = f;
  document.querySelectorAll('.filter-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.filter === f);
  });
  renderDomainTable();
}

document.querySelectorAll('.filter-btn').forEach(btn => {
  btn.addEventListener('click', () => setFilter(btn.dataset.filter));
});

document.getElementById('search-input').addEventListener('input', e => {
  state.search = e.target.value;
  renderDomainTable();
});

// Domain table action delegation
document.getElementById('domain-tbody').addEventListener('click', async e => {
  const btn = e.target.closest('[data-action]');
  if (!btn) return;
  const action = btn.dataset.action;
  const id     = parseInt(btn.dataset.id);
  const fqdn   = btn.dataset.fqdn;

  if (action === 'delete') {
    confirm_(`Delete domain "${fqdn}"? The certificate is not revoked.`, async () => {
      await DELETE(`/api/domains/${id}`);
      await loadDomains();
    });
  } else if (action === 'issue' || action === 'renew') {
    openLogModal(id, action, fqdn);
  }
});

// ── Add Domain modal ────────────────────────────────────────────────────────────────────

const addDomainOverlay = document.getElementById('add-domain-overlay');

function openAddDomain() {
  const profSel = document.getElementById('ad-profile');
  const cfSel   = document.getElementById('ad-cf-zone');

  profSel.innerHTML = state.cpProfiles.length
    ? state.cpProfiles.map(p => `<option value="${p.id}">${escHtml(p.profile_name)}</option>`).join('')
    : '<option value="">— No profiles saved —</option>';

  cfSel.innerHTML = state.cfZones.length
    ? state.cfZones.map(z => `<option value="${z.id}">${escHtml(z.zone_name)}</option>`).join('')
    : '<option value="">— No zones saved —</option>';

  document.getElementById('ad-root').value    = '';
  document.getElementById('ad-subdomain').value = '';
  document.getElementById('ad-wildcard').checked = false;
  document.getElementById('ad-fqdn-preview').textContent = '';
  document.querySelector('[name="ad-record-type"][value="apex"]').checked = true;
  document.getElementById('ad-subdomain-group').classList.add('hidden');
  document.getElementById('ad-wildcard-group').classList.remove('hidden');
  document.getElementById('ad-error').classList.add('hidden');

  addDomainOverlay.classList.remove('hidden');
}

document.getElementById('add-domain-btn').addEventListener('click', openAddDomain);
document.getElementById('close-add-domain').addEventListener('click', () => addDomainOverlay.classList.add('hidden'));
document.getElementById('cancel-add-domain').addEventListener('click', () => addDomainOverlay.classList.add('hidden'));

document.querySelectorAll('[name="ad-record-type"]').forEach(radio => {
  radio.addEventListener('change', () => {
    const isApex = document.querySelector('[name="ad-record-type"]:checked').value === 'apex';
    document.getElementById('ad-subdomain-group').classList.toggle('hidden', isApex);
    document.getElementById('ad-wildcard-group').classList.toggle('hidden', !isApex);
    updateFqdnPreview();
  });
});

function updateFqdnPreview() {
  const root = document.getElementById('ad-root').value.trim().toLowerCase();
  const isApex = document.querySelector('[name="ad-record-type"]:checked').value === 'apex';
  const sub = document.getElementById('ad-subdomain').value.trim().toLowerCase();
  const preview = document.getElementById('ad-fqdn-preview');

  if (!root) { preview.textContent = ''; return; }
  const fqdn = isApex ? root : (sub ? `${sub}.${root}` : root);
  preview.textContent = `→ ${fqdn}`;
}

document.getElementById('ad-root').addEventListener('input', updateFqdnPreview);
document.getElementById('ad-subdomain').addEventListener('input', updateFqdnPreview);

document.getElementById('save-add-domain').addEventListener('click', async () => {
  const root      = document.getElementById('ad-root').value.trim();
  const isApex    = document.querySelector('[name="ad-record-type"]:checked').value === 'apex';
  const subdomain = isApex ? null : document.getElementById('ad-subdomain').value.trim() || null;
  const wildcard  = document.getElementById('ad-wildcard').checked && isApex;
  const profileId = parseInt(document.getElementById('ad-profile').value);
  const zoneId    = parseInt(document.getElementById('ad-cf-zone').value);
  const deployTgt = document.getElementById('ad-deploy-target').value;
  const errEl     = document.getElementById('ad-error');

  if (!root) { showErr(errEl, 'Root domain is required.'); return; }
  if (!isApex && !subdomain) { showErr(errEl, 'Subdomain label is required.'); return; }
  if (!profileId) { showErr(errEl, 'Select a cPanel profile.'); return; }
  if (!zoneId)    { showErr(errEl, 'Select a Cloudflare zone.'); return; }

  try {
    await POST('/api/domains', {
      root_domain: root,
      subdomain,
      is_wildcard: wildcard,
      cpanel_profile_id: profileId,
      cloudflare_zone_id: zoneId,
      deploy_target: deployTgt,
    });
    addDomainOverlay.classList.add('hidden');
    await loadDomains();
  } catch (e) {
    showErr(errEl, e.message);
  }
});

// ── Live log modal ─────────────────────────────────────────────────────────────────────────────

const logOverlay = document.getElementById('log-overlay');
let _activeSSE = null;

function openLogModal(domainId, operation, fqdn) {
  document.getElementById('log-modal-title').textContent =
    `${operation === 'issue' ? 'Issuing' : 'Renewing'}: ${fqdn}`;
  const terminal = document.getElementById('log-terminal');
  terminal.innerHTML = '';
  document.getElementById('log-status-text').textContent = 'Running…';
  document.getElementById('log-spinner').style.display = 'block';
  document.getElementById('close-log-btn').disabled = true;
  document.getElementById('close-log').disabled = true;

  logOverlay.classList.remove('hidden');

  if (_activeSSE) { _activeSSE.close(); _activeSSE = null; }

  const url = `/api/domains/${domainId}/${operation}`;
  const es = new EventSource(url);
  _activeSSE = es;

  es.onmessage = e => {
    const msg = JSON.parse(e.data);
    if (msg.type === 'log') {
      appendLogLine(terminal, msg.line, '');
    } else if (msg.type === 'error') {
      appendLogLine(terminal, msg.line, 'error');
    } else if (msg.type === 'done') {
      es.close();
      _activeSSE = null;
      document.getElementById('log-spinner').style.display = 'none';
      if (msg.status === 'ACTIVE') {
        document.getElementById('log-status-text').textContent =
          `Done — certificate active. Expires: ${msg.expiry || 'unknown'}`;
        appendLogLine(terminal, `\n✓ Certificate issued successfully. Expires: ${msg.expiry || 'unknown'}`, 'success');
      } else {
        document.getElementById('log-status-text').textContent = 'Operation failed — see log above.';
        appendLogLine(terminal, '\n✗ Operation failed.', 'error');
      }
      document.getElementById('close-log-btn').disabled = false;
      document.getElementById('close-log').disabled = false;
      loadDomains();
    }
  };

  es.onerror = () => {
    es.close();
    _activeSSE = null;
    appendLogLine(terminal, '\n[Connection lost]', 'error');
    document.getElementById('log-spinner').style.display = 'none';
    document.getElementById('log-status-text').textContent = 'Connection error.';
    document.getElementById('close-log-btn').disabled = false;
    document.getElementById('close-log').disabled = false;
  };
}

function appendLogLine(terminal, text, cls) {
  const span = document.createElement('span');
  span.className = `log-line${cls ? ' ' + cls : ''}`;
  span.textContent = text;
  terminal.appendChild(span);
  terminal.scrollTop = terminal.scrollHeight;
}

function closeLogModal() {
  if (_activeSSE) { _activeSSE.close(); _activeSSE = null; }
  logOverlay.classList.add('hidden');
}

document.getElementById('close-log').addEventListener('click', () => {
  if (!document.getElementById('close-log').disabled) closeLogModal();
});
document.getElementById('close-log-btn').addEventListener('click', closeLogModal);

// ── Credentials ───────────────────────────────────────────────────────────────────────────

async function loadCredentials() {
  try {
    const [cfZones, cpProfiles] = await Promise.all([
      GET('/api/credentials/cloudflare'),
      GET('/api/credentials/cpanel'),
    ]);
    state.cfZones    = cfZones;
    state.cpProfiles = cpProfiles;
    renderCFTable();
    renderCPTable();
  } catch (e) {
    console.error('Failed to load credentials', e);
  }
}

// ── Cloudflare zone table ──────────────────────────────────────────────────────────────────────────

function renderCFTable() {
  const tbody = document.getElementById('cf-tbody');
  const empty = document.getElementById('cf-empty');
  if (!state.cfZones.length) {
    tbody.innerHTML = '';
    empty.classList.remove('hidden');
    return;
  }
  empty.classList.add('hidden');
  tbody.innerHTML = state.cfZones.map(z => `
    <tr>
      <td class="td-mono">${escHtml(z.zone_name)}</td>
      <td class="td-mono" style="color:var(--text-dim);font-size:11px">${escHtml(z.cf_zone_id)}</td>
      <td><span class="masked">${z.cf_token}</span></td>
      <td>
        <button class="btn-test" data-cf-test="${z.id}">Test</button>
        <button class="action-btn btn-renew" data-cf-edit="${z.id}">Edit</button>
        <button class="action-btn btn-delete" data-cf-del="${z.id}" data-name="${escHtml(z.zone_name)}">Delete</button>
      </td>
    </tr>
  `).join('');
}

document.getElementById('cf-tbody').addEventListener('click', async e => {
  const testBtn = e.target.closest('[data-cf-test]');
  const editBtn = e.target.closest('[data-cf-edit]');
  const delBtn  = e.target.closest('[data-cf-del]');

  if (testBtn) {
    const id = parseInt(testBtn.dataset.cfTest);
    testBtn.textContent = 'Testing…';
    testBtn.className = 'btn-test';
    try {
      const res = await POST(`/api/credentials/cloudflare/${id}/test`);
      if (res.ok) {
        testBtn.textContent = `✓ OK (${res.zone_name || 'verified'})`;
        testBtn.className = 'btn-test pass';
      } else {
        testBtn.textContent = `✗ ${res.error}`;
        testBtn.className = 'btn-test fail';
      }
    } catch (err) {
      testBtn.textContent = `✗ ${err.message}`;
      testBtn.className = 'btn-test fail';
    }
  }

  if (editBtn) {
    const id = parseInt(editBtn.dataset.cfEdit);
    const z  = state.cfZones.find(z => z.id === id);
    if (!z) return;
    state.editingCfId = id;
    document.getElementById('cf-modal-title').textContent = 'Edit Cloudflare Zone';
    document.getElementById('cf-zone-name').value = z.zone_name;
    document.getElementById('cf-zone-id').value   = z.cf_zone_id;
    document.getElementById('cf-token').value      = '';
    document.getElementById('cf-token').placeholder = 'Leave blank to keep existing token';
    document.getElementById('cf-modal-error').classList.add('hidden');
    document.getElementById('cf-modal-overlay').classList.remove('hidden');
  }

  if (delBtn) {
    const id   = parseInt(delBtn.dataset.cfDel);
    const name = delBtn.dataset.name;
    confirm_(`Delete Cloudflare zone "${name}"?`, async () => {
      await DELETE(`/api/credentials/cloudflare/${id}`);
      await loadCredentials();
    });
  }
});

// CF modal
const cfOverlay = document.getElementById('cf-modal-overlay');

document.getElementById('add-cf-btn').addEventListener('click', () => {
  state.editingCfId = null;
  document.getElementById('cf-modal-title').textContent = 'Add Cloudflare Zone';
  document.getElementById('cf-zone-name').value = '';
  document.getElementById('cf-zone-id').value   = '';
  document.getElementById('cf-token').value      = '';
  document.getElementById('cf-token').placeholder = 'Write-once — never shown again';
  document.getElementById('cf-modal-error').classList.add('hidden');
  cfOverlay.classList.remove('hidden');
});

document.getElementById('close-cf-modal').addEventListener('click', () => cfOverlay.classList.add('hidden'));
document.getElementById('cancel-cf-modal').addEventListener('click', () => cfOverlay.classList.add('hidden'));

document.getElementById('save-cf-modal').addEventListener('click', async () => {
  const name   = document.getElementById('cf-zone-name').value.trim();
  const zoneId = document.getElementById('cf-zone-id').value.trim();
  const token  = document.getElementById('cf-token').value.trim();
  const errEl  = document.getElementById('cf-modal-error');

  if (!name)   { showErr(errEl, 'Zone name is required.'); return; }
  if (!zoneId) { showErr(errEl, 'Zone ID is required.'); return; }
  if (!state.editingCfId && !token) { showErr(errEl, 'API token is required.'); return; }

  try {
    if (state.editingCfId) {
      const body = { zone_name: name, cf_zone_id: zoneId };
      if (token) body.cf_token = token;
      await PUT(`/api/credentials/cloudflare/${state.editingCfId}`, body);
    } else {
      await POST('/api/credentials/cloudflare', { zone_name: name, cf_zone_id: zoneId, cf_token: token });
    }
    cfOverlay.classList.add('hidden');
    await loadCredentials();
  } catch (e) {
    showErr(errEl, e.message);
  }
});

// ── cPanel profile table ────────────────────────────────────────────────────────────────────────

function renderCPTable() {
  const tbody = document.getElementById('cp-tbody');
  const empty = document.getElementById('cp-empty');
  if (!state.cpProfiles.length) {
    tbody.innerHTML = '';
    empty.classList.remove('hidden');
    return;
  }
  empty.classList.add('hidden');
  tbody.innerHTML = state.cpProfiles.map(p => `
    <tr>
      <td>${escHtml(p.profile_name)}</td>
      <td class="td-mono" style="font-size:12px">${escHtml(p.cpanel_hostname)}</td>
      <td class="td-mono" style="font-size:12px">${escHtml(p.cpanel_username)}</td>
      <td style="font-size:11px;color:var(--text-dim)">${p.auth_method === 'api_token' ? 'API Token' : 'Password'}</td>
      <td><span class="masked">${p.credential}</span></td>
      <td style="font-size:11px;color:var(--text-dim)">${escHtml(p.addon_domain_suffix || '—')}</td>
      <td>
        <button class="btn-test" data-cp-test="${p.id}">Test</button>
        <button class="action-btn btn-renew" data-cp-edit="${p.id}">Edit</button>
        <button class="action-btn btn-delete" data-cp-del="${p.id}" data-name="${escHtml(p.profile_name)}">Delete</button>
      </td>
    </tr>
  `).join('');
}

document.getElementById('cp-tbody').addEventListener('click', async e => {
  const testBtn = e.target.closest('[data-cp-test]');
  const editBtn = e.target.closest('[data-cp-edit]');
  const delBtn  = e.target.closest('[data-cp-del]');

  if (testBtn) {
    const id = parseInt(testBtn.dataset.cpTest);
    testBtn.textContent = 'Testing…';
    testBtn.className = 'btn-test';
    try {
      const res = await POST(`/api/credentials/cpanel/${id}/test`);
      if (res.ok) {
        testBtn.textContent = '✓ Connected';
        testBtn.className = 'btn-test pass';
      } else {
        testBtn.textContent = `✗ ${res.error}`;
        testBtn.className = 'btn-test fail';
      }
    } catch (err) {
      testBtn.textContent = `✗ ${err.message}`;
      testBtn.className = 'btn-test fail';
    }
  }

  if (editBtn) {
    const id = parseInt(editBtn.dataset.cpEdit);
    const p  = state.cpProfiles.find(p => p.id === id);
    if (!p) return;
    state.editingCpId = id;
    state.cpAuthMethod = p.auth_method;

    document.getElementById('cp-modal-title').textContent = 'Edit cPanel Profile';
    document.getElementById('cp-name').value        = p.profile_name;
    document.getElementById('cp-hostname').value    = p.cpanel_hostname;
    document.getElementById('cp-username').value    = p.cpanel_username;
    document.getElementById('cp-credential').value  = '';
    document.getElementById('cp-credential').placeholder = 'Leave blank to keep existing credential';
    document.getElementById('cp-cred-label').textContent = p.auth_method === 'api_token' ? 'API Token' : 'Password';
    document.getElementById('cp-addon-suffix').value = p.addon_domain_suffix || '';
    updateAuthToggleUI();
    document.getElementById('cp-modal-error').classList.add('hidden');
    document.getElementById('cp-modal-overlay').classList.remove('hidden');
  }

  if (delBtn) {
    const id   = parseInt(delBtn.dataset.cpDel);
    const name = delBtn.dataset.name;
    confirm_(`Delete cPanel profile "${name}"?`, async () => {
      await DELETE(`/api/credentials/cpanel/${id}`);
      await loadCredentials();
    });
  }
});

// CP modal
const cpOverlay = document.getElementById('cp-modal-overlay');

document.getElementById('add-cp-btn').addEventListener('click', () => {
  state.editingCpId = null;
  state.cpAuthMethod = 'api_token';
  document.getElementById('cp-modal-title').textContent = 'Add cPanel Profile';
  document.getElementById('cp-name').value        = '';
  document.getElementById('cp-hostname').value    = '';
  document.getElementById('cp-username').value    = '';
  document.getElementById('cp-credential').value  = '';
  document.getElementById('cp-credential').placeholder = 'Write-once — never shown again';
  document.getElementById('cp-cred-label').textContent = 'API Token';
  document.getElementById('cp-addon-suffix').value = '';
  updateAuthToggleUI();
  document.getElementById('cp-modal-error').classList.add('hidden');
  cpOverlay.classList.remove('hidden');
});

document.getElementById('close-cp-modal').addEventListener('click', () => cpOverlay.classList.add('hidden'));
document.getElementById('cancel-cp-modal').addEventListener('click', () => cpOverlay.classList.add('hidden'));

document.querySelectorAll('.auth-toggle-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    state.cpAuthMethod = btn.dataset.auth;
    updateAuthToggleUI();
  });
});

function updateAuthToggleUI() {
  document.querySelectorAll('.auth-toggle-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.auth === state.cpAuthMethod);
  });
  document.getElementById('cp-cred-label').textContent =
    state.cpAuthMethod === 'api_token' ? 'API Token' : 'Password';
}

document.getElementById('save-cp-modal').addEventListener('click', async () => {
  const name        = document.getElementById('cp-name').value.trim();
  const hostname    = document.getElementById('cp-hostname').value.trim();
  const username    = document.getElementById('cp-username').value.trim();
  const credential  = document.getElementById('cp-credential').value.trim();
  const addonSuffix = document.getElementById('cp-addon-suffix').value.trim();
  const errEl       = document.getElementById('cp-modal-error');

  if (!name)     { showErr(errEl, 'Profile name is required.'); return; }
  if (!hostname) { showErr(errEl, 'Hostname is required.'); return; }
  if (!username) { showErr(errEl, 'Username is required.'); return; }
  if (!state.editingCpId && !credential) { showErr(errEl, 'Credential is required.'); return; }

  try {
    const body = {
      profile_name: name,
      cpanel_hostname: hostname,
      cpanel_username: username,
      auth_method: state.cpAuthMethod,
      addon_domain_suffix: addonSuffix || null,
    };
    if (credential) body.credential = credential;

    if (state.editingCpId) {
      await PUT(`/api/credentials/cpanel/${state.editingCpId}`, body);
    } else {
      await POST('/api/credentials/cpanel', body);
    }
    cpOverlay.classList.add('hidden');
    await loadCredentials();
  } catch (e) {
    showErr(errEl, e.message);
  }
});

// ── Renewal History ─────────────────────────────────────────────────────────────────────────

async function loadHistory() {
  const domain = document.getElementById('history-search').value.trim();
  const result = document.getElementById('history-result-filter').value;
  const params = new URLSearchParams();
  if (domain) params.set('domain', domain);
  if (result) params.set('result', result);

  try {
    const records = await GET(`/api/history?${params}`);
    state.history = records;
    renderHistoryTable();
  } catch (e) {
    console.error('Failed to load history', e);
  }
}

function renderHistoryTable() {
  const tbody = document.getElementById('history-tbody');
  const empty = document.getElementById('history-empty');

  if (!state.history.length) {
    tbody.innerHTML = '';
    empty.classList.remove('hidden');
    return;
  }
  empty.classList.add('hidden');

  tbody.innerHTML = state.history.map(h => {
    const rc = h.result === 'success'
      ? '<span class="result-success">SUCCESS</span>'
      : '<span class="result-failure">FAILURE</span>';
    const by = h.triggered_by === 'manual' ? 'Manual' : 'Scheduler';
    const hasLog = h.log_output && h.log_output.trim().length > 0;
    const expandBtn = hasLog
      ? `<button class="expand-btn" data-expand="${h.id}">▶ View log</button>`
      : '—';

    return `<tr id="hist-row-${h.id}">
      <td class="td-mono" style="font-size:11px;white-space:nowrap">${fmtDatetime(h.created_at)}</td>
      <td class="td-mono" style="font-size:12px">${escHtml(h.domain_fqdn)}</td>
      <td>${rc}</td>
      <td style="font-size:12px;color:var(--text-dim)">${by}</td>
      <td>${expandBtn}</td>
    </tr>
    ${hasLog ? `<tr id="hist-log-${h.id}" class="hidden"><td colspan="5"><div class="history-log-expand" style="display:block">${escHtml(h.log_output)}</div></td></tr>` : ''}`;
  }).join('');
}

document.getElementById('history-tbody').addEventListener('click', e => {
  const btn = e.target.closest('[data-expand]');
  if (!btn) return;
  const id     = btn.dataset.expand;
  const logRow = document.getElementById(`hist-log-${id}`);
  if (!logRow) return;
  const hidden = logRow.classList.toggle('hidden');
  btn.textContent = hidden ? '▶ View log' : '▼ Hide log';
});

document.getElementById('history-search').addEventListener('input', loadHistory);
document.getElementById('history-result-filter').addEventListener('change', loadHistory);

document.getElementById('clear-history-btn').addEventListener('click', () => {
  confirm_('Clear all renewal history? This cannot be undone.', async () => {
    await DELETE('/api/history');
    await loadHistory();
  });
});

// ── Confirm dialog ────────────────────────────────────────────────────────────────────────────

let _confirmCallback = null;

function confirm_(message, callback) {
  document.getElementById('confirm-message').textContent = message;
  _confirmCallback = callback;
  document.getElementById('confirm-overlay').classList.remove('hidden');
}

document.getElementById('confirm-cancel').addEventListener('click', () => {
  _confirmCallback = null;
  document.getElementById('confirm-overlay').classList.add('hidden');
});

document.getElementById('confirm-ok').addEventListener('click', async () => {
  document.getElementById('confirm-overlay').classList.add('hidden');
  if (_confirmCallback) {
    try { await _confirmCallback(); } catch (e) { console.error('Confirm action failed', e); }
    _confirmCallback = null;
  }
});

// ── Utility ─────────────────────────────────────────────────────────────────────────────

function escHtml(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function showErr(el, msg) {
  el.textContent = msg;
  el.classList.remove('hidden');
}

// ── Bootstrap ───────────────────────────────────────────────────────────────────────────────

(async function init() {
  await loadDomains();
})();
