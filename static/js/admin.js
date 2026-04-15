// ── State ──────────────────────────────────────────────────────────────────
let allProducts  = [];
let newImageFiles = [];    // files staged for upload
let editingId    = null;
let pendingDelete = null;

// ── DOM refs ───────────────────────────────────────────────────────────────
const productForm       = document.getElementById('productForm');
const formTitle         = document.getElementById('formTitle');
const submitBtn         = document.getElementById('submitBtn');
const cancelEditBtn     = document.getElementById('cancelEditBtn');
const formMsg           = document.getElementById('formMsg');
const fName             = document.getElementById('fName');
const fCategory         = document.getElementById('fCategory');
const fWeight           = document.getElementById('fWeight');
const fSpecs            = document.getElementById('fSpecs');
const fNotes            = document.getElementById('fNotes');
const imgDropZone       = document.getElementById('imgDropZone');
const imgInput          = document.getElementById('imgInput');
const imgPreviewGrid    = document.getElementById('imgPreviewGrid');
const existingImagesGroup = document.getElementById('existingImagesGroup');
const existingImagesGrid  = document.getElementById('existingImagesGrid');
const productListEl     = document.getElementById('productList');
const productCountEl    = document.getElementById('productCount');
const searchInput       = document.getElementById('searchInput');
const deleteModal       = document.getElementById('deleteModal');
const deleteModalMsg    = document.getElementById('deleteModalMsg');
const confirmDeleteBtn  = document.getElementById('confirmDeleteBtn');
const cancelDeleteBtn   = document.getElementById('cancelDeleteBtn');

// ── Init ───────────────────────────────────────────────────────────────────
loadProducts();

// ── Image staging ──────────────────────────────────────────────────────────

imgDropZone.addEventListener('click', () => imgInput.click());
imgDropZone.addEventListener('dragover', e => {
  e.preventDefault(); imgDropZone.classList.add('drag-over');
});
imgDropZone.addEventListener('dragleave', () => imgDropZone.classList.remove('drag-over'));
imgDropZone.addEventListener('drop', e => {
  e.preventDefault(); imgDropZone.classList.remove('drag-over');
  addFiles(Array.from(e.dataTransfer.files));
});
imgInput.addEventListener('change', () => {
  addFiles(Array.from(imgInput.files));
  imgInput.value = '';
});

function addFiles(files) {
  files.filter(f => f.type.startsWith('image/')).forEach(f => {
    newImageFiles.push(f);
    renderNewThumb(f, newImageFiles.length - 1);
  });
}

function renderNewThumb(file, idx) {
  const url  = URL.createObjectURL(file);
  const wrap = document.createElement('div');
  wrap.className = 'img-thumb-wrap';
  wrap.dataset.idx = idx;
  wrap.innerHTML = `
    <img src="${url}" alt="preview" />
    ${idx === 0 && !editingId ? '<span class="primary-badge">Primary</span>' : ''}
    <button class="remove-img" type="button">✕</button>`;
  wrap.querySelector('.remove-img').addEventListener('click', () => {
    newImageFiles.splice(idx, 1);
    refreshNewPreviews();
  });
  imgPreviewGrid.appendChild(wrap);
}

function refreshNewPreviews() {
  imgPreviewGrid.innerHTML = '';
  newImageFiles.forEach((f, i) => renderNewThumb(f, i));
}

// ── Form submit ────────────────────────────────────────────────────────────

productForm.addEventListener('submit', async e => {
  e.preventDefault();
  if (!fName.value.trim()) { showMsg('Product name is required.', 'error'); return; }

  const fd = new FormData();
  fd.append('name',     fName.value.trim());
  fd.append('category', fCategory.value.trim());
  fd.append('weight',   fWeight.value.trim());
  fd.append('specs',    fSpecs.value.trim());
  fd.append('notes',    fNotes.value.trim());

  const fieldName = editingId ? 'new_images' : 'images';
  newImageFiles.forEach(f => fd.append(fieldName, f));

  submitBtn.disabled = true;
  submitBtn.textContent = editingId ? 'Saving…' : 'Adding…';

  try {
    const url    = editingId ? `/api/products/${editingId}` : '/api/products';
    const method = editingId ? 'PUT' : 'POST';
    const res    = await fetch(url, { method, body: fd });
    const data   = await res.json();

    if (!res.ok) throw new Error(data.detail || 'Server error');

    showMsg(editingId ? 'Product updated!' : 'Product added!', 'success');
    resetForm();
    loadProducts();
  } catch (err) {
    showMsg(err.message, 'error');
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = editingId ? 'Save Changes' : 'Add Product';
  }
});

function showMsg(text, type) {
  formMsg.textContent = text;
  formMsg.className   = `form-msg ${type}`;
  formMsg.classList.remove('hidden');
  setTimeout(() => formMsg.classList.add('hidden'), 3500);
}

// ── Cancel edit ────────────────────────────────────────────────────────────

cancelEditBtn.addEventListener('click', resetForm);

function resetForm() {
  editingId = null;
  productForm.reset();
  newImageFiles = [];
  imgPreviewGrid.innerHTML = '';
  existingImagesGroup.classList.add('hidden');
  existingImagesGrid.innerHTML = '';
  formTitle.textContent   = 'Add New Product';
  submitBtn.textContent   = 'Add Product';
  cancelEditBtn.classList.add('hidden');
}

// ── Load product list ──────────────────────────────────────────────────────

async function loadProducts() {
  const res  = await fetch('/api/products');
  allProducts = await res.json();
  renderList(allProducts);
  productCountEl.textContent = allProducts.length;
}

searchInput.addEventListener('input', () => {
  const q = searchInput.value.toLowerCase();
  renderList(allProducts.filter(p =>
    p.name.toLowerCase().includes(q) ||
    (p.category || '').toLowerCase().includes(q)
  ));
});

function renderList(products) {
  if (!products.length) {
    productListEl.innerHTML = '<p class="empty-msg">No products found.</p>';
    return;
  }
  productListEl.innerHTML = products.map(p => {
    const thumb = p.primary_image
      ? `<img class="product-thumb" src="/uploads/${p.primary_image}" alt="${esc(p.name)}" />`
      : `<div class="product-thumb-placeholder">📦</div>`;
    const meta = [
      p.category ? `<span>📁 ${esc(p.category)}</span>` : '',
      p.weight   ? `<span>⚖️ ${esc(p.weight)}</span>`   : '',
    ].filter(Boolean).join('');
    return `
      <div class="product-item" data-id="${p.id}">
        ${thumb}
        <div class="product-info">
          <h3>${esc(p.name)}</h3>
          <div class="product-meta">${meta}</div>
        </div>
        <div class="product-actions">
          <button class="btn btn-ghost btn-sm" onclick="startEdit(${p.id})">Edit</button>
          <button class="btn btn-danger btn-sm" onclick="startDelete(${p.id}, '${esc(p.name)}')">Delete</button>
        </div>
      </div>`;
  }).join('');
}

// ── Edit ───────────────────────────────────────────────────────────────────

async function startEdit(id) {
  const res     = await fetch(`/api/products/${id}`);
  const product = await res.json();

  editingId = id;
  fName.value     = product.name;
  fCategory.value = product.category || '';
  fWeight.value   = product.weight   || '';
  fSpecs.value    = product.specs    || '';
  fNotes.value    = product.notes    || '';

  newImageFiles   = [];
  imgPreviewGrid.innerHTML = '';

  // Show existing images
  if (product.images && product.images.length) {
    existingImagesGroup.classList.remove('hidden');
    existingImagesGrid.innerHTML = product.images.map(img => `
      <div class="img-thumb-wrap" id="existing-${img.id}">
        <img src="/uploads/${img.filename}" alt="" />
        ${img.is_primary ? '<span class="primary-badge">Primary</span>' : ''}
        <button class="remove-img" type="button"
          onclick="deleteExistingImage(${id}, ${img.id})">✕</button>
      </div>`).join('');
  } else {
    existingImagesGroup.classList.add('hidden');
  }

  formTitle.textContent = 'Edit Product';
  submitBtn.textContent = 'Save Changes';
  cancelEditBtn.classList.remove('hidden');

  // Scroll form into view
  productForm.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

async function deleteExistingImage(productId, imageId) {
  if (!confirm('Remove this image?')) return;
  await fetch(`/api/products/${productId}/images/${imageId}`, { method: 'DELETE' });
  document.getElementById(`existing-${imageId}`)?.remove();
}

// ── Delete ─────────────────────────────────────────────────────────────────

function startDelete(id, name) {
  pendingDelete = id;
  deleteModalMsg.textContent = `"${name}" will be permanently deleted.`;
  deleteModal.classList.remove('hidden');
}

cancelDeleteBtn.addEventListener('click', () => {
  pendingDelete = null;
  deleteModal.classList.add('hidden');
});

confirmDeleteBtn.addEventListener('click', async () => {
  if (!pendingDelete) return;
  await fetch(`/api/products/${pendingDelete}`, { method: 'DELETE' });
  deleteModal.classList.add('hidden');
  pendingDelete = null;
  if (editingId) resetForm();
  loadProducts();
});

// ── Util ───────────────────────────────────────────────────────────────────
function esc(str) {
  return String(str)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}
