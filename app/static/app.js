const statusEl = document.getElementById('status');
const tbody = document.querySelector('#results tbody');
const app = document.getElementById('app');
const loginCard = document.getElementById('loginCard');
const sourceAuthStatusEl = document.getElementById('sourceAuthStatus');

let statusTimeoutId = null;

function setStatus(msg, level='success'){
  statusEl.textContent = msg;
  statusEl.className = level === 'success' ? 'ok' : (level === 'warning' ? 'status-warn' : 'err');

  if (statusTimeoutId) {
    clearTimeout(statusTimeoutId);
  }

  const timeoutMs = level === 'success' ? 5000 : 10000;
  statusTimeoutId = setTimeout(() => {
    statusEl.textContent = '';
    statusEl.className = '';
    statusTimeoutId = null;
  }, timeoutMs);
}

async function doSearch() {
  const query = document.getElementById('query').value.trim();
  if (!query) return setStatus('Enter a query', 'warning');
  const media_type = document.getElementById('mediaType').value;
  const sort = document.getElementById('sort').value;
  const search_in = [...document.querySelectorAll('input[type=checkbox]:checked')].map(x=>x.value);
  const resp = await fetch('/api/search', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({query, media_type, sort, search_in})});
  const data = await resp.json();
  if (!resp.ok) return setStatus(data.detail || 'Search failed', 'error');
  renderResults(data.results || []);
}

function formatDynamicState(state) {
  if (!state || Object.keys(state).length === 0) return 'No refresh recorded';
  const parts = [];
  if (state.status_code) parts.push(`HTTP ${state.status_code}`);
  if (state.ok === true) parts.push('ok');
  if (state.cooldown === true) parts.push('cooldown');
  if (state.message) parts.push(state.message);
  if (state.ip) parts.push(`IP ${state.ip}`);
  if (state.asn) parts.push(`ASN ${state.asn}`);
  if (state.as) parts.push(state.as);
  if (state.last_attempt_at) parts.push(`last attempt ${state.last_attempt_at}`);
  return parts.join(' • ') || 'No refresh recorded';
}

async function loadSourceAuthStatus() {
  if (!sourceAuthStatusEl) return;
  try {
    const resp = await fetch('/api/source-auth/status');
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || 'Failed to load source auth status');
    sourceAuthStatusEl.textContent = `Cookie configured: ${data.mam_cookie_configured ? 'yes' : 'no'} • mam_id present: ${data.mam_id_present ? 'yes' : 'no'} • Dynamic seedbox: ${data.dynamic_seedbox_enabled ? 'enabled' : 'disabled'} • ${formatDynamicState(data.last_dynamic_seedbox_refresh)}`;
  } catch (error) {
    sourceAuthStatusEl.textContent = 'Unable to load source auth status';
  }
}

async function refreshDynamicSeedbox() {
  const button = document.getElementById('refreshSeedboxBtn');
  if (button) button.disabled = true;
  try {
    const resp = await fetch('/api/source-auth/dynamic-seedbox-refresh', {method:'POST'});
    const data = await resp.json();
    const failed = !resp.ok || data.ok === false;
    if (failed && data.cooldown !== true) {
      setStatus(data.message || data.detail || 'Dynamic seedbox refresh failed', 'error');
      await loadSourceAuthStatus();
      return;
    }
    if (data.cooldown === true) {
      setStatus(data.message || 'Dynamic seedbox refresh skipped due to cooldown', 'warning');
    } else {
      setStatus(data.message || (data.ok ? 'Dynamic seedbox refreshed' : 'Dynamic seedbox refresh completed'));
    }
    await loadSourceAuthStatus();
  } finally {
    if (button) button.disabled = false;
  }
}

async function saveMamCookie() {
  const input = document.getElementById('mamCookieInput');
  const cookie = input?.value.trim() || '';
  if (!cookie) return setStatus('Paste a MAM API cookie/token first', 'warning');
  const resp = await fetch('/api/source-auth/cookie', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({cookie})});
  if (input) input.value = '';
  const data = await resp.json();
  if (!resp.ok) return setStatus(data.detail || 'Failed to save cookie/token', 'error');
  setStatus('MAM API cookie/token saved');
  await loadSourceAuthStatus();
}

function appendLabeledValue(container, label, value) {
  const row = document.createElement('div');
  const labelEl = document.createElement('span');
  labelEl.className = 'field-label';
  labelEl.textContent = `${label}:`;
  row.appendChild(labelEl);
  row.appendChild(document.createTextNode(` ${value || '-'}`));
  container.appendChild(row);
}

function createBadge(text, className) {
  const badge = document.createElement('span');
  badge.className = `badge ${className}`;
  badge.textContent = text;
  return badge;
}


function abbreviateProvider(provider) {
  if ((provider || '').toLowerCase() === 'audiobookshelf') {
    return 'ABS';
  }
  return provider;
}

function buildLibraryMatchDetails(matches) {
  return (matches || []).map(match => {
    const provider = (match.provider || '').trim();
    const details = [match.title, match.author, match.narrator]
      .map(value => (value || '').trim())
      .filter(Boolean);
    if (details.length === 0) {
      return provider;
    }
    if (!provider) {
      return details.join(' | ');
    }
    return `${provider}: ${details.join(' | ')}`;
  }).filter(Boolean);
}


function getLibraryProviders(matches) {
  return [...new Set((matches || [])
    .map(match => abbreviateProvider((match.provider || '').trim()))
    .filter(Boolean))];
}


function buildPresenceLabel(result) {
  const parts = [];
  if (result.in_qbit === true) {
    parts.push('qbit');
  }
  parts.push(...getLibraryProviders(result.library_matches || []));

  if (parts.length > 0) {
    return `in ${parts.join(' + ')}`;
  }
  if (result.in_library === true) {
    return 'in library';
  }
  return '';
}

function buildPresenceTooltip(result, label) {
  const details = [];
  if (result.in_qbit === true) {
    details.push(result.qbit_name ? `qBittorrent: ${result.qbit_name}` : 'qBittorrent');
  }
  details.push(...buildLibraryMatchDetails(result.library_matches || []));
  return details.length ? details.join('\n') : label;
}

function confirmLibraryGrab(result) {
  const details = buildLibraryMatchDetails(result.library_matches || []);

  return new Promise(resolve => {
    const overlay = document.createElement('div');
    overlay.className = 'confirm-overlay';

    const dialog = document.createElement('div');
    dialog.className = 'confirm-dialog';
    dialog.setAttribute('role', 'dialog');
    dialog.setAttribute('aria-modal', 'true');
    dialog.setAttribute('aria-labelledby', 'library-confirm-title');
    dialog.setAttribute('aria-describedby', 'library-confirm-message');

    const title = document.createElement('h2');
    title.id = 'library-confirm-title';
    title.textContent = 'Grab anyway?';

    const message = document.createElement('p');
    message.id = 'library-confirm-message';
    message.textContent = 'This appears to already be in your library.';

    const actions = document.createElement('div');
    actions.className = 'confirm-actions';

    const cancelButton = document.createElement('button');
    cancelButton.type = 'button';
    cancelButton.className = 'confirm-cancel';
    cancelButton.textContent = 'Cancel';

    const grabButton = document.createElement('button');
    grabButton.type = 'button';
    grabButton.textContent = 'Grab anyway';

    actions.append(cancelButton, grabButton);
    dialog.append(title, message);

    if (details.length > 0) {
      const list = document.createElement('ul');
      list.className = 'confirm-match-list';
      details.forEach(detail => {
        const item = document.createElement('li');
        item.textContent = detail;
        list.appendChild(item);
      });
      dialog.appendChild(list);
    }

    dialog.appendChild(actions);
    overlay.appendChild(dialog);

    const close = confirmed => {
      document.removeEventListener('keydown', onKeydown);
      overlay.remove();
      resolve(confirmed);
    };

    const onKeydown = event => {
      if (event.key === 'Escape') {
        close(false);
      }
    };

    cancelButton.addEventListener('click', () => close(false));
    grabButton.addEventListener('click', () => close(true));
    overlay.addEventListener('click', event => {
      if (event.target === overlay) {
        close(false);
      }
    });
    document.addEventListener('keydown', onKeydown);
    document.body.appendChild(overlay);
    cancelButton.focus();
  });
}

function renderResults(results){
  tbody.innerHTML = '';
  const mediaType = document.getElementById('mediaType').value;

  results.filter(r => (r.seeders || 0) > 0).forEach(r => {
    const flags = [];
    if (!r.free) flags.push('not freeleech');
    if (r.my_snatched) flags.push('already snatched');
    if ((r.size || '').toLowerCase().includes('gib') && parseFloat(r.size) > 2) flags.push('very large');

    const tr = document.createElement('tr');

    const titleTd = document.createElement('td');
    const titleDiv = document.createElement('div');
    titleDiv.className = 'book-title';
    titleDiv.textContent = r.title || '';
    const subDiv = document.createElement('div');
    subDiv.className = 'book-sub';
    subDiv.textContent = r.catname || '';
    titleTd.append(titleDiv, subDiv);

    const detailsTd = document.createElement('td');
    appendLabeledValue(detailsTd, 'Author', r.author);
    appendLabeledValue(detailsTd, 'Narrator', r.narrator);
    appendLabeledValue(detailsTd, 'Series', r.series);
    const formatRow = document.createElement('div');
    const formatLabel = document.createElement('span');
    formatLabel.className = 'field-label';
    formatLabel.textContent = 'Format:';
    formatRow.appendChild(formatLabel);
    const formatParts = [r.filetypes, r.filetype].filter(Boolean);
    const formatText = formatParts.length ? formatParts.join(' • ') : '-';
    const sizeSuffix = r.size ? ` • ${r.size}` : '';
    formatRow.appendChild(document.createTextNode(` ${formatText}${sizeSuffix}`));
    detailsTd.appendChild(formatRow);

    const statusTd = document.createElement('td');
    const availabilityRow = document.createElement('div');
    availabilityRow.className = 'status-row';
    const availabilityLabel = document.createElement('span');
    availabilityLabel.className = 'field-label';
    availabilityLabel.textContent = 'Availability:';
    const seeders = document.createElement('span');
    seeders.className = 'peer-pill';
    seeders.textContent = `${r.seeders} seeders`;
    const leechers = document.createElement('span');
    leechers.className = 'peer-muted';
    leechers.textContent = `${r.leechers} leechers`;
    availabilityRow.append(availabilityLabel, document.createTextNode(' '), seeders, document.createTextNode(' '), leechers);

    const highlightsRow = document.createElement('div');
    highlightsRow.className = 'status-row';
    const highlightsLabel = document.createElement('span');
    highlightsLabel.className = 'field-label';
    highlightsLabel.textContent = 'Highlights:';
    highlightsRow.appendChild(highlightsLabel);

    let hasHighlight = false;
    flags.forEach(flag => {
      hasHighlight = true;
      highlightsRow.appendChild(document.createTextNode(' '));
      highlightsRow.appendChild(createBadge(flag, 'warn'));
    });
    if (r.free) {
      hasHighlight = true;
      highlightsRow.appendChild(document.createTextNode(' '));
      highlightsRow.appendChild(createBadge('freeleech', 'ok'));
    }
    if (r.vip) {
      hasHighlight = true;
      highlightsRow.appendChild(document.createTextNode(' '));
      highlightsRow.appendChild(createBadge('vip', 'vip'));
    }
    if (!hasHighlight) {
      highlightsRow.appendChild(document.createTextNode(' -'));
    }

    statusTd.append(availabilityRow, highlightsRow);

    const actionTd = document.createElement('td');
    actionTd.className = 'action-cell';
    const button = document.createElement('button');
    button.className = 'add-btn';
    button.dataset.id = String(r.id);
    button.dataset.media = mediaType;

    if (r.in_qbit === true) {
      button.textContent = 'Loaded';
      button.disabled = true;
      button.title = r.qbit_name ? `Already loaded in qBittorrent as ${r.qbit_name}` : 'Already loaded in qBittorrent';
    } else {
      button.textContent = 'Grab';
      button.onclick = event => doAdd(event, r);
    }
    actionTd.appendChild(button);

    const presenceLabel = buildPresenceLabel(r);
    if (presenceLabel) {
      const presence = document.createElement('div');
      presence.className = 'qbit-loaded-label';
      presence.setAttribute('role', 'status');
      presence.setAttribute('aria-label', presenceLabel);
      presence.title = buildPresenceTooltip(r, presenceLabel);
      presence.textContent = presenceLabel;
      actionTd.appendChild(presence);
    }

    tr.append(titleTd, detailsTd, statusTd, actionTd);
    tbody.appendChild(tr);
  });
}

async function doAdd(evt, result){
  const button = evt.currentTarget;
  if (button.dataset.addPending === 'true') {
    return;
  }

  const id = Number(button.dataset.id);
  const media_type = button.dataset.media;
  const resetDelayMs = 1500;

  button.dataset.addPending = 'true';

  if (result?.in_library === true) {
    button.disabled = true;
    button.textContent = 'Confirm...';

    if (!(await confirmLibraryGrab(result))) {
      delete button.dataset.addPending;
      button.disabled = false;
      button.textContent = 'Grab';
      return;
    }
  }

  button.disabled = true;
  button.classList.add('is-adding');
  button.textContent = 'Adding...';

  try {
    const resp = await fetch('/api/add', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({id, media_type})});
    const data = await resp.json();

    if (!resp.ok) {
      button.classList.remove('is-adding');
      button.classList.add('is-failed');
      button.textContent = 'Failed';
      setStatus(data.detail || 'Add failed', 'error');
      return;
    }

    button.classList.remove('is-adding');
    button.classList.add('is-success');
    button.textContent = 'Success';
    setStatus(data.message || 'Added');
  } catch (error) {
    button.classList.remove('is-adding');
    button.classList.add('is-failed');
    button.textContent = 'Failed';
    setStatus('Add failed', 'error');
  } finally {
    setTimeout(() => {
      delete button.dataset.addPending;
      button.disabled = false;
      button.classList.remove('is-adding', 'is-success', 'is-failed');
      button.textContent = 'Grab';
    }, resetDelayMs);
  }
}

document.getElementById('searchBtn')?.addEventListener('click', doSearch);
document.getElementById('refreshSeedboxBtn')?.addEventListener('click', refreshDynamicSeedbox);
document.getElementById('saveMamCookieBtn')?.addEventListener('click', saveMamCookie);
loadSourceAuthStatus();
document.getElementById('mediaType').value = window.DEFAULTS.mediaType || 'audiobook';
document.getElementById('sort').value = window.DEFAULTS.sort || 'seedersDesc';

document.getElementById('loginBtn')?.addEventListener('click', async () => {
  const username = document.getElementById('username').value;
  const password = document.getElementById('password').value;
  const resp = await fetch('/login', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({username,password})});
  const data = await resp.json();
  if (!resp.ok) return setStatus(data.detail || 'Login failed', 'error');
  app.classList.remove('hidden');
  loginCard?.classList.add('hidden');
  setStatus('Logged in');
  loadSourceAuthStatus();
});
