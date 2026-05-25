const statusEl = document.getElementById('status');
const tbody = document.querySelector('#results tbody');
const app = document.getElementById('app');

function setStatus(msg, isErr=false){ statusEl.textContent = msg; statusEl.className = isErr ? 'err' : 'ok'; }

async function doSearch() {
  const query = document.getElementById('query').value.trim();
  if (!query) return setStatus('Enter a query', true);
  const media_type = document.getElementById('mediaType').value;
  const sort = document.getElementById('sort').value;
  const search_in = [...document.querySelectorAll('input[type=checkbox]:checked')].map(x=>x.value);
  const resp = await fetch('/api/search', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({query, media_type, sort, search_in})});
  const data = await resp.json();
  if (!resp.ok) return setStatus(data.detail || 'Search failed', true);
  renderResults(data.results || []);
}

function renderResults(results){
  tbody.innerHTML = '';
  results.forEach(r => {
    const flags = [];
    if (r.seeders === 0) flags.push('0 seeders');
    if (!r.free) flags.push('not freeleech');
    if (r.my_snatched) flags.push('already snatched');
    if ((r.size || '').toLowerCase().includes('gib') && parseFloat(r.size) > 2) flags.push('very large');
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${r.title}<br/><small>${r.catname||''}</small></td>
      <td>A:${r.author||'-'}<br/>N:${r.narrator||'-'}<br/>S:${r.series||'-'}<br/>${r.filetypes||''} | ${r.size||''}</td>
      <td>${r.seeders}/${r.leechers}</td>
      <td>${flags.map(f=>`<span class='badge warn'>${f}</span>`).join('')} ${r.free?"<span class='badge ok'>free</span>":''} ${r.vip?"<span class='badge vip'>vip</span>":''}</td>
      <td><button data-id='${r.id}' data-media='${document.getElementById('mediaType').value}'>Add</button></td>`;
    tr.querySelector('button').onclick = doAdd;
    tbody.appendChild(tr);
  });
}

async function doAdd(evt){
  const id = Number(evt.target.dataset.id);
  const media_type = evt.target.dataset.media;
  const resp = await fetch('/api/add', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({id, media_type})});
  const data = await resp.json();
  if (!resp.ok) return setStatus(data.detail || 'Add failed', true);
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
  if (!resp.ok) return setStatus(data.detail || 'Login failed', true);
  app.classList.remove('hidden');
  setStatus('Logged in');
});
