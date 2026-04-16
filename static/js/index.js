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

  // Show animated loading with step indicators
  loadingCard.classList.remove('hidden');
  loadingCard.innerHTML = `
    <div class="loading-spinner"></div>
    <p class="loading-text">Analyzing photo…</p>
    <p class="loading-sub">Step 1 of 2: Finding catalog page</p>`;
  resultCard.classList.add('hidden');

  const fd = new FormData();
  fd.append('photo', selectedFile);

  // Simulate step 2 message after ~2s
  const stepTimer = setTimeout(() => {
    const sub = loadingCard.querySelector('.loading-sub');
    if (sub) sub.textContent = 'Step 2 of 2: Reading catalog page…';
  }, 2500);

  try {
    const res  = await fetch('/api/identify', { method: 'POST', body: fd });
    const data = await res.json();
    clearTimeout(stepTimer);
    renderResult(data);
  } catch {
    clearTimeout(stepTimer);
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

  if (data.matched && data.product_code) {
    // Full match: product identified with code, specs, and catalog page
    const details = [
      data.dimensions ? `<div class="spec-row"><span class="spec-label">Dimensions</span><span class="spec-value">${esc(data.dimensions)}</span></div>` : '',
      data.weight     ? `<div class="spec-row"><span class="spec-label">Weight</span><span class="spec-value">${esc(data.weight)}</span></div>` : '',
      data.specs      ? `<div class="spec-row"><span class="spec-label">Material</span><span class="spec-value">${esc(data.specs)}</span></div>` : '',
      data.category   ? `<div class="spec-row"><span class="spec-label">Category</span><span class="spec-value">${esc(data.category)}</span></div>` : '',
    ].filter(Boolean).join('');

    resultCard.innerHTML = `
      <div class="result-matched">

        <div class="result-header">
          ${confidenceBadge(data.confidence)}
        </div>

        <div class="product-identity">
          <div class="product-code-block">
            <span class="product-code-label">Product Code</span>
            <span class="product-code">${esc(data.product_code)}</span>
          </div>
          <h2 class="product-full-name">${esc(data.product_name || data.product_code)}</h2>
        </div>

        ${details ? `<div class="spec-grid">${details}</div>` : ''}

        ${data.reason ? `<p class="result-reason">"${esc(data.reason)}"</p>` : ''}

        <div class="catalog-section">
          <div class="catalog-section-header">
            <span class="catalog-page-tag">📖 Catalog — Page ${esc(data.page_number)}</span>
            <span class="catalog-zoom-hint">Tap to zoom</span>
          </div>
          <div class="catalog-page-wrap">
            <img
              class="catalog-page-img"
              src="${esc(data.image_url)}"
              alt="Catalog page ${esc(data.page_number)}"
              onclick="openLightbox(this.src, '${esc(data.product_code)} — Page ${esc(data.page_number)}')"
            />
          </div>
        </div>

        <button class="btn btn-ghost btn-search-again" onclick="resetAll()">
          🔍 Search Again
        </button>
      </div>`;

  } else if (data.image_url) {
    // Page found but couldn't pin exact product — show the page anyway
    resultCard.innerHTML = `
      <div class="result-matched">
        <div class="result-header">
          <span class="result-badge badge-warn">~ Partial match</span>
        </div>
        <p class="result-reason" style="margin-bottom:12px">
          ${esc(data.reason || 'Found the likely catalog page — check below for your product.')}
        </p>
        <div class="catalog-section">
          <div class="catalog-section-header">
            <span class="catalog-page-tag">📖 Catalog — Page ${esc(data.page_number)} · ${esc(data.category)}</span>
            <span class="catalog-zoom-hint">Tap to zoom</span>
          </div>
          <div class="catalog-page-wrap">
            <img
              class="catalog-page-img"
              src="${esc(data.image_url)}"
              alt="Catalog page ${esc(data.page_number)}"
              onclick="openLightbox(this.src, 'Page ${esc(data.page_number)} — ${esc(data.category)}')"
            />
          </div>
        </div>
        <button class="btn btn-ghost btn-search-again" onclick="resetAll()">🔍 Search Again</button>
      </div>`;

  } else {
    // No match at all
    const msg = data.message || data.reason || 'No matching product found.';
    resultCard.innerHTML = `
      <div class="result-no-match">
        <div class="no-match-icon">🔎</div>
        <h3>No Match Found</h3>
        <p>${esc(msg)}</p>
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

// ── Lightbox ───────────────────────────────────────────────────────────────

function openLightbox(src, caption) {
  const existing = document.getElementById('lightboxOverlay');
  if (existing) existing.remove();

  const overlay = document.createElement('div');
  overlay.id = 'lightboxOverlay';
  overlay.className = 'lightbox-overlay';
  overlay.innerHTML = `
    <div class="lightbox-inner">
      <button class="lightbox-close" onclick="document.getElementById('lightboxOverlay').remove()">✕</button>
      <img src="${esc(src)}" alt="${esc(caption)}" />
      ${caption ? `<p class="lightbox-caption">${esc(caption)}</p>` : ''}
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
