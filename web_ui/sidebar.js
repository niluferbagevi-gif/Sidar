/* ─── Başlangıç ve Oturumlar (Sessions) ─────────────────── */
async function loadSessions() {
  try {
    const res = await fetchAPI(apiUrl('/sessions'));
    const data = await res.json();
    currentSessionId = data.active_session;
    allSessions = data.sessions || [];
    renderSessionList(allSessions);
  } catch (err) {
    console.error("Oturumlar yüklenemedi:", err);
  }
}

function formatRelTime(ts) {
  if (!ts) return '';
  const diffSec = Math.floor((Date.now() / 1000) - ts);
  if (diffSec < 60)  return 'az önce';
  if (diffSec < 3600) return `${Math.floor(diffSec/60)} dk önce`;
  if (diffSec < 86400) return `${Math.floor(diffSec/3600)} sa önce`;
  if (diffSec < 604800) return `${Math.floor(diffSec/86400)} gün önce`;
  return `${Math.floor(diffSec/604800)} hf önce`;
}

function renderSessionList(sessions) {
  const listEl = document.getElementById('session-list');
  listEl.innerHTML = '';
  if (!sessions || sessions.length === 0) return;
  sessions.forEach(s => {
    const isActive = s.id === currentSessionId;
    const div = document.createElement('div');
    div.className = `session-item ${isActive ? 'active' : ''}`;
    div.onclick = () => selectSession(s.id);
    const userCount = s.user_count || 0;
    const astCount  = s.asst_count || 0;
    const relTime   = formatRelTime(s.updated_at);
    const statsHtml = (userCount > 0 || astCount > 0)
      ? `<span class="diff-add">+${userCount}</span><span class="diff-del">-${astCount}</span>`
      : '';
    div.innerHTML = `
      <div class="session-item-main">
        <div class="session-item-title" title="${escHtml(s.title)}">${escHtml(s.title)}</div>
        <div class="session-item-stats">
          ${statsHtml}
          <span class="session-time">${relTime}</span>
        </div>
      </div>
      <button class="session-item-delete" onclick="deleteSession('${s.id}', event)" title="Sohbeti Sil">
        <svg width="13" height="13" viewBox="0 0 16 16" fill="currentColor">
          <path d="M5.5 1a.5.5 0 0 0-.5.5v1h6v-1a.5.5 0 0 0-.5-.5h-5ZM2 3.5a.5.5 0 0 1 .5-.5h11a.5.5 0 0 1 0 1h-1v9a2 2 0 0 1-2 2h-5a2 2 0 0 1-2-2v-9h-1a.5.5 0 0 1-.5-.5Zm3 1v9a1 1 0 0 0 1 1h5a1 1 0 0 0 1-1v-9H5Z"/>
        </svg>
      </button>`;
    listEl.appendChild(div);
  });
}

function filterSessions(q) {
  if (!q.trim()) {
    renderSessionList(allSessions);
    return;
  }
  const lower = q.toLowerCase();
  renderSessionList(allSessions.filter(s => s.title.toLowerCase().includes(lower)));
}

async function selectSession(id) {
  if (id === currentSessionId) {
    showChatPanel();
    return;
  }
  currentSessionId = id;
  await loadSessionHistory(id, true);
}

async function loadSessionHistory(id, switchToChat = false) {
  try {
    const res = await fetchAPI(`/sessions/${id}`);
    const data = await res.json();
    
    if (data.success) {
      document.getElementById('messages').innerHTML = '';
      msgCounter = 0;
      
      if (data.history && data.history.length > 0) {
        data.history.forEach(msg => {
          if (msg.role === 'user') {
            appendUser(msg.content);
          } else if (msg.role === 'assistant') {
            const msgId = createSidarMsg();
            finalizeMsg(msgId, msg.content);
          }
        });
      }
      loadSessions(); // Menüdeki renk vurgusunu (active) güncelle
      if (switchToChat) showChatPanel();
    }
  } catch (err) {
    console.error("Geçmiş yüklenemedi:", err);
  }
}

async function createNewSession() {
  try {
    const res = await fetchAPI('/sessions/new', { method: 'POST' });
    const data = await res.json();
    if (data.success) {
      currentSessionId = data.session_id;
      document.getElementById('messages').innerHTML = '';
      document.getElementById('task-input').value = '';
      document.getElementById('input-area').value = '';
      msgCounter = 0;
      await loadSessions();
      showTaskPanel();
    }
  } catch (err) {
    console.error("Yeni sohbet oluşturulamadı:", err);
  }
}

async function deleteSession(id, event) {
  event.stopPropagation();
  if (!confirm('Bu sohbet kalıcı olarak silinecek. Emin misiniz?')) return;
  try {
    const res = await fetchAPI(`/sessions/${id}`, { method: 'DELETE' });
    const data = await res.json();
    if (data.success) {
      if (currentSessionId === id) {
         document.getElementById('messages').innerHTML = '';
         showTaskPanel();
      }
      await loadSessions();
      if (data.active_session && currentSessionId === id) {
         currentSessionId = data.active_session;
         loadSessionHistory(currentSessionId, false);
      }
    }
  } catch (err) {
    console.error("Sohbet silinemedi:", err);
  }
}

/* ─── Panel geçişleri ───────────────────────────────────── */
function setActiveTopNav(tabId) {
  document.querySelectorAll('.nav-tab').forEach((t) => t.classList.remove('active'));
  document.getElementById(tabId)?.classList.add('active');
}

function hideSecondaryPanels() {
  const dashboard = document.getElementById('dashboard-panel');
  const admin = document.getElementById('admin-panel-container');
  if (dashboard) dashboard.style.display = 'none';
  if (admin) admin.style.display = 'none';
}

function showTaskPanel() {
  document.getElementById('task-panel').style.display = 'flex';
  document.getElementById('chat-panel').style.display = 'none';
  hideSecondaryPanels();
  setActiveTopNav('tasks-nav-tab');
}

function showChatPanel() {
  document.getElementById('task-panel').style.display = 'none';
  document.getElementById('chat-panel').style.display = 'flex';
  hideSecondaryPanels();
  setActiveTopNav('chat-nav-tab');
  document.getElementById('input-area').focus();
}

/* ─── Branch Seçici ─────────────────────────────────────── */
let _cachedBranches = null;

async function openRepoModal() {
  document.getElementById('repo-search').value = '';
  document.getElementById('repo-modal').classList.add('open');

  if (!_cachedRepos) {
    document.getElementById('repo-list').innerHTML =
      '<div style="padding:14px;color:var(--text-dim);font-size:12px">Depolar yükleniyor…</div>';
    try {
      const ownerHint = (currentRepo || '').includes('/') ? currentRepo.split('/')[0] : '';
      const data = await (await fetchAPI(`/github-repos?owner=${encodeURIComponent(ownerHint)}`)).json();
      _cachedRepos = data.repos || [];
    } catch {
      _cachedRepos = [];
    }
  }

  renderRepos(_cachedRepos);
  setTimeout(() => document.getElementById('repo-search').focus(), 50);
}

function renderRepos(list) {
  if (!list || list.length === 0) {
    document.getElementById('repo-list').innerHTML =
      '<div style="padding:14px;color:var(--text-dim);font-size:12px">Gösterilecek repo bulunamadı.</div>';
    return;
  }
  document.getElementById('repo-list').innerHTML = list.map(r => {
    const name = r.full_name || '';
    const selected = name === currentRepo ? 'selected' : '';
    const defBranch = r.default_branch || 'main';
    const privacy = r.private === 'true' ? 'private' : 'public';
    return `
    <div class="repo-item ${selected}" onclick="selectRepo('${name}')">
      <div class="repo-item-icon" style="font-size:17px">📁</div>
      <div class="repo-item-info">
        <div class="repo-item-name">${escHtml(name)}</div>
        <div class="repo-item-meta">${escHtml(defBranch)} · ${privacy}</div>
      </div>
      <span class="repo-item-check">✓</span>
    </div>`;
  }).join('');
}

function filterRepos(q) {
  const query = q.toLowerCase();
  renderRepos((_cachedRepos || []).filter(r => (r.full_name || '').toLowerCase().includes(query)));
}

async function selectRepo(name) {
  closeModal('repo-modal');
  if (!name || name === currentRepo) return;

  try {
    const res = await fetchAPI('/set-repo', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ repo: name }),
    });
    const data = await res.json();
    if (!data.success) {
      alert(`Repo değiştirilemedi: ${data.message || data.error || 'Bilinmeyen hata'}`);
      return;
    }
  } catch (e) {
    console.warn('Repo API hatası:', e);
    alert('Sunucuya bağlanılamadı, repo değiştirilemedi.');
    return;
  }

  currentRepo = name;
  _cachedBranches = null; // Repo değişince dal listesi önbelleğini sıfırla
  document.getElementById('repo-label').textContent = name;
  const srl = document.getElementById('sidebar-repo-label');
  if (srl) srl.textContent = name.split('/').pop() || name;

  const prHead = document.getElementById('pr-head')?.textContent || currentBranch || defaultBranch;
  const viewBtn = document.getElementById('pr-view-btn');
  if (viewBtn && name) {
    viewBtn.href = `https://github.com/${name}/compare/${defaultBranch}...${prHead}`;
    viewBtn.style.display = 'inline-flex';
  }
}

async function openBranchModal() {
  document.getElementById('branch-search').value = '';
  document.getElementById('branch-modal').classList.add('open');

  // Gerçek dal listesini sunucudan çek (oturum boyunca önbelleğe al)
  if (!_cachedBranches) {
    document.getElementById('branch-list').innerHTML =
      '<div style="padding:14px;color:var(--text-dim);font-size:12px">Dallar yükleniyor…</div>';
    try {
      const data      = await (await fetchAPI('/git-branches')).json();
      _cachedBranches = data.branches || ['main'];
    } catch {
      _cachedBranches = [currentBranch || 'main'];
    }
  }

  renderBranches(_cachedBranches);
  setTimeout(() => document.getElementById('branch-search').focus(), 50);
}

function renderBranches(list) {
  const container = document.getElementById('branch-list');
  container.innerHTML = list.map(b => `
    <div class="repo-item ${b === currentBranch ? 'selected' : ''}" data-branch="${escHtml(b)}">
      <div class="repo-item-icon" style="font-size:18px">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="var(--text-dim)">
          <path d="M11.75 2.5a.75.75 0 1 0 0 1.5.75.75 0 0 0 0-1.5Zm-2.25.75a2.25 2.25 0 1 1 3 2.122V6A2.5 2.5 0 0 1 10 8.5H6a1 1 0 0 0-1 1v1.128a2.251 2.251 0 1 1-1.5 0V5.372a2.25 2.25 0 1 1 1.5 0v1.836A2.492 2.492 0 0 1 6 7h4a1 1 0 0 0 1-1v-.628A2.25 2.25 0 0 1 9.5 3.25ZM4.25 12a.75.75 0 1 0 0 1.5.75.75 0 0 0 0-1.5ZM3.5 3.25a.75.75 0 1 1 1.5 0 .75.75 0 0 1-1.5 0Z"/>
        </svg>
      </div>
      <div class="repo-item-info">
        <div class="repo-item-name">${escHtml(b)}</div>
      </div>
      <span class="repo-item-check">✓</span>
    </div>`).join('');
  // inline onclick yerine event delegation — özel karakterli dal adlarını güvenle iletir
  container.onclick = e => {
    const item = e.target.closest('[data-branch]');
    if (item) selectBranch(item.dataset.branch);
  };
}

function filterBranches(q) {
  renderBranches((_cachedBranches || [currentBranch]).filter(
    b => b.toLowerCase().includes(q.toLowerCase())
  ));
}

async function selectBranch(name) {
  closeModal('branch-modal');

  // Backend'e git checkout isteği gönder
  try {
    const res  = await fetchAPI('/set-branch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ branch: name }),
    });
    const data = await res.json();
    if (!data.success) {
      console.warn('Dal değiştirilemedi:', data.error);
      alert(`Dal değiştirilemedi: ${data.error}`);
      return;
    }
  } catch (e) {
    console.warn('Dal API hatası:', e);
    alert('Sunucuya bağlanılamadı, dal değiştirilemedi.');
    return;
  }

  // Başarılı: UI güncelle
  currentBranch = name;
  _cachedBranches = null; // Dal listesi önbelleğini sıfırla

  document.getElementById('branch-label').textContent = name;
  const sbl = document.getElementById('sidebar-branch-label');
  if (sbl) sbl.textContent = name;

  // PR çubuğunu güncelle
  const prBar = document.getElementById('pr-bar');
  if (prBar) {
    if (name && name !== defaultBranch) {
      document.getElementById('pr-base').textContent = defaultBranch;
      document.getElementById('pr-head').textContent = name;
      const viewBtn = document.getElementById('pr-view-btn');
      if (viewBtn && currentRepo) {
        viewBtn.href = `https://github.com/${currentRepo}/compare/${defaultBranch}...${name}`;
      }
      prBar.style.display = 'flex';
    } else {
      prBar.style.display = 'none';
    }
  }
}

/* ─── Akıllı PR Oluşturma ────────────────────────────────── */
function createSmartPR() {
  const branch = currentBranch || document.getElementById('pr-head')?.textContent || '';
  if (!branch || branch === 'main' || branch === 'master') {
    quickTask('Mevcut branch için git diff analiz edip akıllı PR oluştur');
    return;
  }
  const btn = document.getElementById('pr-create-btn');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Oluşturuluyor…'; }
  const msg = `"${branch}" branch'i için git diff ve commit geçmişini analiz ederek otomatik PR oluştur`;
  const taskInput = document.getElementById('task-input');
  if (taskInput) taskInput.value = msg;
  // startTask() butonu geri aktif edecek (yanıt tamamlandıktan sonra)
  startTask();
  setTimeout(() => {
    if (btn) { btn.disabled = false; btn.textContent = '✨ PR Oluştur'; }
  }, 15000);
}

/* ─── Oturum Dışa Aktarma ────────────────────────────────── */
async function exportSession(format) {
  if (!currentSessionId) { alert('Aktif oturum yok.'); return; }
  try {
    const data = await (await fetchAPI(`/sessions/${currentSessionId}`)).json();
    if (!data.success) { alert('Oturum verisi alınamadı.'); return; }
    const history = data.history || [];
    const title = (document.querySelector('.session-item.active .session-item-title')
                    || {textContent: 'sidar-oturum'}).textContent.trim().replace(/\s+/g, '-');

    let content, mime, ext;
    if (format === 'json') {
      content = JSON.stringify({ title, session_id: currentSessionId, messages: history }, null, 2);
      mime = 'application/json'; ext = 'json';
    } else {
      const lines = [`# ${title}\n`];
      for (const msg of history) {
        const role = msg.role === 'user' ? '**Kullanıcı**' : '**Sidar**';
        lines.push(`${role}\n\n${msg.content}\n\n---\n`);
      }
      content = lines.join('\n');
      mime = 'text/markdown'; ext = 'md';
    }

    const blob = new Blob([content], { type: mime });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `${title}.${ext}`;
    a.click();
    URL.revokeObjectURL(a.href);
  } catch (e) {
    alert(`Dışa aktarma hatası: ${e.message}`);
  }
}

/* ─── Mobil Sidebar Toggle ───────────────────────────────── */
function toggleSidebar() {
  const sidebar  = document.querySelector('.sidebar');
  const overlay  = document.getElementById('sidebar-overlay');
  const isOpen   = sidebar.classList.toggle('open');
  overlay.classList.toggle('active', isOpen);
}