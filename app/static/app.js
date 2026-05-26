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

function renderResults(results){
  tbody.innerHTML = '';
  results.filter(r => (r.seeders || 0) > 0).forEach(r => {
    const flags = [];
    if (!r.free) flags.push('not freeleech');
    if (r.my_snatched) flags.push('already snatched');
    if ((r.size || '').toLowerCase().includes('gib') && parseFloat(r.size) > 2) flags.push('very large');
    const tr = document.createElement('tr');
    tr.innerHTML = `<td><div class='book-title'>${r.title}</div><div class='book-sub'>${r.catname||''}</div></td>
      <td><div><span class='field-label'>Author:</span> ${r.author||'-'}</div><div><span class='field-label'>Narrator:</span> ${r.narrator||'-'}</div><div><span class='field-label'>Series:</span> ${r.series||'-'}</div><div><span class='field-label'>Format:</span> ${r.filetypes||''} ${r.size?`• ${r.size}`:''}</div></td>
      <td><span class='peer-pill'>${r.seeders} seeders</span><br/><span class='peer-muted'>${r.leechers} leechers</span></td>
      <td>${flags.map(f=>`<span class='badge warn'>${f}</span>`).join('')} ${r.free?"<span class='badge ok'>freeleech</span>":''} ${r.vip?"<span class='badge vip'>vip</span>":''}</td>
      <td><button class='add-btn' data-id='${r.id}' data-media='${document.getElementById('mediaType').value}'>Add to queue</button></td>`;
    tr.querySelector('button').onclick = doAdd;
    tbody.appendChild(tr);
  });
}

async function doAdd(evt){
  const id = Number(evt.target.dataset.id);
  const media_type = evt.target.dataset.media;
  const resp = await fetch('/api/add', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({id, media_type})});
  const data = await resp.json();
  if (!resp.ok) return setStatus(data.detail || 'Add failed', 'error');
  setStatus(data.message || 'Added');
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
