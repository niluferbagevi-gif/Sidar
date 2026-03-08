/* ─── RAG Belge Deposu Modalı ───────────────────────────── */
function openRagModal() {
  document.getElementById('rag-modal').classList.add('open');
  ragTab('belgeler');
  ragLoadDocs();
}

function closeRagModal() {
  document.getElementById('rag-modal').classList.remove('open');
}

function ragTab(name) {
  document.querySelectorAll('.rag-tab').forEach(t => t.classList.toggle('active', t.dataset.tab === name));
  document.querySelectorAll('.rag-pane').forEach(p => p.classList.toggle('active', p.dataset.pane === name));
}

async function ragLoadDocs(filterText) {
  const list = document.getElementById('rag-doc-list');
  list.innerHTML = '<div class="rag-empty">Yükleniyor…</div>';
  try {
    const data = await (await fetch('/rag/docs')).json();
    const docs = data.docs || [];
    const q = (filterText || '').toLowerCase().trim();
    const filtered = q ? docs.filter(d =>
      (d.title || '').toLowerCase().includes(q) ||
      (d.source || '').toLowerCase().includes(q)
    ) : docs;

    if (!filtered.length) {
      list.innerHTML = '<div class="rag-empty">Henüz belge eklenmemiş.</div>';
      return;
    }

    list.innerHTML = filtered.map(d => {
      const icon = (d.source || '').startsWith('http') ? '🔗' : '📄';
      const size = d.size ? `${(d.size / 1000).toFixed(1)}k karakter` : '';
      const meta = [size, d.source ? escHtml(d.source.replace(/^.*\//, '').substring(0, 50)) : ''].filter(Boolean).join(' · ');
      return `<div class="rag-doc-item">
        <span class="rag-doc-icon">${icon}</span>
        <div class="rag-doc-info">
          <div class="rag-doc-title">${escHtml(d.title || d.id)}</div>
          <div class="rag-doc-meta">${meta}</div>
          ${d.preview ? `<div class="rag-doc-preview">${escHtml(d.preview)}</div>` : ''}
        </div>
        <div class="rag-doc-actions">
          <button class="rag-btn danger" onclick="ragDeleteDoc('${escHtml(d.id)}')" title="Sil">🗑</button>
        </div>
      </div>`;
    }).join('');
  } catch (err) {
    list.innerHTML = `<div class="rag-empty">Hata: ${escHtml(err.message)}</div>`;
  }
}

async function ragDeleteDoc(docId) {
  if (!confirm(`"${docId}" belgesi silinsin mi?`)) return;
  try {
    const res = await fetch(`/rag/docs/${encodeURIComponent(docId)}`, { method: 'DELETE' });
    const data = await res.json();
    ragShowResult('rag-del-result', data.success, data.message || data.detail || 'Silindi.');
    if (data.success) ragLoadDocs(document.getElementById('rag-filter').value);
  } catch (err) {
    ragShowResult('rag-del-result', false, err.message);
  }
}

async function ragAddFile() {
  const path  = document.getElementById('rag-file-path').value.trim();
  const title = document.getElementById('rag-file-title').value.trim();
  if (!path) { ragShowResult('rag-add-result', false, 'Dosya yolu gerekli.'); return; }
  const btn = document.getElementById('rag-add-file-btn');
  btn.disabled = true; btn.textContent = 'Ekleniyor…';
  try {
    const res = await fetch('/rag/add-file', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ path, title: title || undefined })
    });
    const data = await res.json();
    ragShowResult('rag-add-result', data.success, data.message || data.detail || 'Tamamlandı.');
    if (data.success) { document.getElementById('rag-file-path').value = ''; document.getElementById('rag-file-title').value = ''; }
  } catch (err) {
    ragShowResult('rag-add-result', false, err.message);
  } finally {
    btn.disabled = false; btn.textContent = 'Ekle';
  }
}

async function ragAddUrl() {
  const url   = document.getElementById('rag-url-input').value.trim();
  const title = document.getElementById('rag-url-title').value.trim();
  if (!url) { ragShowResult('rag-add-result', false, 'URL gerekli.'); return; }
  const btn = document.getElementById('rag-add-url-btn');
  btn.disabled = true; btn.textContent = 'Ekleniyor…';
  try {
    const res = await fetch('/rag/add-url', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ url, title: title || undefined })
    });
    const data = await res.json();
    ragShowResult('rag-add-result', data.success, data.message || data.detail || 'Tamamlandı.');
    if (data.success) { document.getElementById('rag-url-input').value = ''; document.getElementById('rag-url-title').value = ''; }
  } catch (err) {
    ragShowResult('rag-add-result', false, err.message);
  } finally {
    btn.disabled = false; btn.textContent = 'Ekle';
  }
}

async function ragSearch() {
  const q = document.getElementById('rag-search-q').value.trim();
  if (!q) return;
  const out = document.getElementById('rag-search-out');
  out.textContent = 'Aranıyor…';
  try {
    const res = await fetch(`/rag/search?q=${encodeURIComponent(q)}`);
    const data = await res.json();
    out.textContent = data.result || 'Sonuç bulunamadı.';
  } catch (err) {
    out.textContent = `Hata: ${err.message}`;
  }
}

function ragShowResult(elId, ok, msg) {
  const el = document.getElementById(elId);
  if (!el) return;
  el.className = `rag-result ${ok ? 'ok' : 'err'}`;
  el.textContent = msg;
  el.style.display = 'block';
  setTimeout(() => { el.style.display = 'none'; }, 6000);
}