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
  previewImg.src = URL.createObjectURL(file);
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
  } catch {
    renderError('Network error. Please try again.');
  } finally {
    identifyBtn.disabled = false;
    loadingCard.classList.add('hidden');
  }
});

// ── Render ─────────────────────────────────────────────────────────────────

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

  if (data.matched && data.image_url) {
    resultCard.innerHTML = `
      <div class="result-matched">
        <div class="result-header">
          ${confidenceBadge(data.confidence)}
          <div class="result-title-block">
            <span class="result-page-label">Catalog Page ${esc(data.page_number)}</span>
            <h2 class="result-product-name">${esc(data.category)}</h2>
          </div>
        </div>

        ${data.reason
          ? `<p class="result-reason">"${esc(data.reason)}"</p>`
          : ''}

        <div class="catalog-page-wrap">
          <img
            class="catalog-page-img"
            src="${esc(data.image_url)}"
            alt="Catalog page ${esc(data.page_number)}"
            onclick="openFullscreen(this)"
            title="Click to view full size"
          />
          <p class="catalog-page-hint">📌 Tap image to view full size</p>
        </div>

        <button class="btn btn-ghost btn-search-again" onclick="resetAll()">
          🔍 Search Again
        </button>
      </div>`;
  } else {
    const msg = data.message || data.reason || 'No matching product found in the catalog.';
    resultCard.innerHTML = `
      <div class="result-no-match">
        <div class="no-match-icon">🔎</div>
        <h3>No Match Found</h3>
        <p>${esc(msg)}</p>
        <button class="btn btn-ghost btn-search-again" onclick="resetAll()">
          Try Another Photo
        </button>
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

// ── Fullscreen lightbox ────────────────────────────────────────────────────

function openFullscreen(img) {
  const overlay = document.createElement('div');
  overlay.className = 'lightbox-overlay';
  overlay.innerHTML = `
    <div class="lightbox-inner">
      <button class="lightbox-close" onclick="this.closest('.lightbox-overlay').remove()">✕</button>
      <img src="${img.src}" alt="${img.alt}" />
    </div>`;
  overlay.addEventListener('click', e => {
    if (e.target === overlay) overlay.remove();
  });
  document.body.appendChild(overlay);
}

function esc(str) {
  return String(str)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
