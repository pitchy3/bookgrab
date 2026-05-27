const statusEl = document.getElementById('status');
const tbody = document.querySelector('#results tbody');
const app = document.getElementById('app');
const loginCard = document.getElementById('loginCard');

let statusTimeoutId = null;

function setStatus(msg, level='success'){
  statusEl.textContent = msg;
  statusEl.className = level === 'success' ? 'ok' : 'err';

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
    const sizeSuffix = r.size ? ` • ${r.size}` : '';
    formatRow.appendChild(document.createTextNode(` ${r.filetypes || ''}${sizeSuffix}`));
    detailsTd.appendChild(formatRow);

    const peersTd = document.createElement('td');
    const seeders = document.createElement('span');
    seeders.className = 'peer-pill';
    seeders.textContent = `${r.seeders} seeders`;
    const br = document.createElement('br');
    const leechers = document.createElement('span');
    leechers.className = 'peer-muted';
    leechers.textContent = `${r.leechers} leechers`;
    peersTd.append(seeders, br, leechers);

    const flagsTd = document.createElement('td');
    flags.forEach(flag => {
      flagsTd.appendChild(createBadge(flag, 'warn'));
      flagsTd.appendChild(document.createTextNode(' '));
    });
    if (r.free) {
      flagsTd.appendChild(createBadge('freeleech', 'ok'));
      flagsTd.appendChild(document.createTextNode(' '));
    }
    if (r.vip) {
      flagsTd.appendChild(createBadge('vip', 'vip'));
    }

    const actionTd = document.createElement('td');
    const button = document.createElement('button');
    button.className = 'add-btn';
    button.dataset.id = String(r.id);
    button.dataset.media = mediaType;
    button.textContent = 'Add to queue';
    button.onclick = doAdd;
    actionTd.appendChild(button);

    tr.append(titleTd, detailsTd, peersTd, flagsTd, actionTd);
    tbody.appendChild(tr);
  });
}

async function doAdd(evt){
  const button = evt.currentTarget;
  const id = Number(button.dataset.id);
  const media_type = button.dataset.media;
  const resetDelayMs = 1500;

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
      button.disabled = false;
      button.classList.remove('is-adding', 'is-success', 'is-failed');
      button.textContent = 'Add to queue';
    }, resetDelayMs);
  }
}

document.getElementById('searchBtn')?.addEventListener('click', doSearch);
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
});
