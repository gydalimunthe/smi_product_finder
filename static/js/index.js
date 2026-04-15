const dropZone    = document.getElementById('dropZone');
const fileInput   = document.getElementById('fileInput');
const previewArea = document.getElementById('previewArea');
const previewImg  = document.getElementById('previewImg');
const identifyBtn = document.getElementById('identifyBtn');
const clearBtn    = document.getElementById('clearBtn');
const loadingCard = document.getElementById('loadingCard');
const resultCard  = document.getElementById('resultCard');

let selectedFile = null;

// ── File selection ─────────────────────────────────────────────────────────

fileInput.addEventListener('change', () => {
  if (fileInput.files[0]) showPreview(fileInput.files[0]);
});

dropZone.addEventListener('dragover', e => {
  e.preventDefault();
  dropZone.classList.add('drag-over');
});
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));
dropZone.addEventListener('drop', e => {
  e.preventDefault();
  dropZone.classList.remove('drag-over');
  const file = e.dataTransfer.files[0];
  if (file && file.type.startsWith('image/')) showPreview(file);
});
dropZone.addEventListener('click', e => {
  if (e.target.tagName !== 'LABEL') fileInput.click();
});

function showPreview(file) {
  selectedFile = file;
  const url = URL.createObjectURL(file);
  previewImg.src = url;
  dropZone.classList.add('hidden');
  previewArea.classList.remove('hidden');
  loadingCard.classList.add('hidden');
  resultCard.classList.add('hidden');
}

clearBtn.addEventListener('click', resetAll);

function resetAll() {
  selectedFile = null;
  previewImg.src = '';
  fileInput.value = '';
  previewArea.classList.add('hidden');
  dropZone.classList.remove('hidden');
  loadingCard.classList.add('hidden');
  resultCard.classList.add('hidden');
}

// ── Identify ───────────────────────────────────────────────────────────────

identifyBtn.addEventListener('click', async () => {
  if (!selectedFile) return;

  identifyBtn.disabled = true;
  loadingCard.classList.remove('hidden');
  resultCard.classList.add('hidden');

  const fd = new FormData();
  fd.append('photo', selectedFile);

  try {
    const res  = await fetch('/api/identify', { method: 'POST', body: fd });
    const data = await res.json();
    renderResult(data);
  } catch (err) {
    renderError('Network error. Please try again.');
  } finally {
    identifyBtn.disabled = false;
    loadingCard.classList.add('hidden');
  }
});

// ── Render result ──────────────────────────────────────────────────────────

function confidenceBadge(level) {
  const map = {
    high:   ['badge-success', '✓ High confidence'],
    medium: ['badge-warn',    '~ Medium confidence'],
    low:    ['badge-danger',  '! Low confidence'],
  };
  const [cls, label] = map[level] || map.medium;
  return `<span class="result-badge ${cls}">${label}</span>`;
}

function renderResult(data) {
  resultCard.classList.remove('hidden');

  if (data.matched && data.product) {
    const p   = data.product;
    const imgs = (p.images || [])
      .slice(0, 4)
      .map(i => `<img src="/uploads/${i.filename}" alt="${p.name}" />`)
      .join('');

    const specs = p.specs
      ? `<div class="result-field"><label>Specs</label><p>${esc(p.specs)}</p></div>` : '';
    const weight = p.weight
      ? `<div class="result-field"><label>Weight</label><p>${esc(p.weight)}</p></div>` : '';
    const category = p.category
      ? `<div class="result-field"><label>Category</label><p>${esc(p.category)}</p></div>` : '';
    const notes = p.notes
      ? `<div class="result-notes">📝 ${esc(p.notes)}</div>` : '';

    resultCard.innerHTML = `
      <div class="result-matched">
        <div class="result-header">
          ${confidenceBadge(data.confidence)}
          <h2 class="result-product-name">${esc(p.name)}</h2>
        </div>
        ${imgs ? `<div class="result-images">${imgs}</div>` : ''}
        <div class="result-grid">
          ${category}${weight}${specs}
        </div>
        ${notes}
        ${data.reason ? `<p class="result-reason">"${esc(data.reason)}"</p>` : ''}
        <button class="btn btn-ghost btn-search-again" onclick="resetAll()">🔍 Search Again</button>
      </div>`;
  } else {
    const desc = data.description || data.message || 'No matching product found in the catalog.';
    resultCard.innerHTML = `
      <div class="result-no-match">
        <div class="no-match-icon">🔎</div>
        <h3>No Match Found</h3>
        <p>${esc(desc)}</p>
        ${data.reason ? `<p class="result-reason" style="margin-top:8px">${esc(data.reason)}</p>` : ''}
        <button class="btn btn-ghost btn-search-again" onclick="resetAll()">Try Another Photo</button>
      </div>`;
  }
}

function renderError(msg) {
  resultCard.classList.remove('hidden');
  resultCard.innerHTML = `
    <div class="result-no-match">
      <div class="no-match-icon">⚠️</div>
      <h3>Something went wrong</h3>
      <p>${esc(msg)}</p>
      <button class="btn btn-ghost btn-search-again" onclick="resetAll()">Try Again</button>
    </div>`;
}

function esc(str) {
  return String(str)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
