// Life Graph AI — Frontend Controller

// Application State
const state = {
    user: JSON.parse(localStorage.getItem('lifegraph_user')) || null,
    apiKey: localStorage.getItem('lifegraph_gemini_key') || '',
    targetRole: 'Frontend Developer',
    documents: [],
    skills: [],
    jobs: [],
    activeView: 'dashboard',
    chatHistory: [],
    queriesCount: parseInt(localStorage.getItem('lifegraph_queries_count') || '0', 10)
};

// Wrapper for fetch requests to inject authentication headers
async function apiFetch(url, options = {}) {
    if (!options.headers) {
        options.headers = {};
    }
    if (state.user && state.user.id) {
        options.headers['X-User-Id'] = String(state.user.id);
    }
    
    // Check Content-Type (don't force json for multipart file uploads)
    if (options.body && !(options.body instanceof FormData) && !options.headers['Content-Type']) {
        options.headers['Content-Type'] = 'application/json';
    }

    const res = await fetch(url, options);
    
    if (res.status === 401) {
        // Session invalid or user deleted, trigger logout redirect
        logout();
        throw new Error("Session expired or invalid. Please sign in again.");
    }
    
    return res;
}

// Initialize App
document.addEventListener('DOMContentLoaded', () => {
    setupAuth();
    initSettings();
    setupNavigation();
    setupGlobalSearch();
    setupDropZone();
    setupChat();
    setupCareer();
    setupSettingsPage();
    setupDocumentViewer();
    
    // Auth Guard check
    if (state.user) {
        showAppWorkspace();
    } else {
        showAuthScreen();
    }
    
    checkServerConnection();
});

// --- 0. AUTHENTICATION MODULE ---
function setupAuth() {
    const tabLogin = document.getElementById('tab-login');
    const tabReg = document.getElementById('tab-register');
    const loginForm = document.getElementById('login-form');
    const regForm = document.getElementById('register-form');
    const logoutBtn = document.getElementById('logout-btn');
    
    // Switch tabs
    tabLogin.addEventListener('click', () => {
        tabLogin.classList.add('active');
        tabReg.classList.remove('active');
        loginForm.style.display = 'flex';
        regForm.style.display = 'none';
        clearAuthAlert();
    });
    
    tabReg.addEventListener('click', () => {
        tabReg.classList.add('active');
        tabLogin.classList.remove('active');
        regForm.style.display = 'flex';
        loginForm.style.display = 'none';
        clearAuthAlert();
    });
    
    // Sign In Submission
    loginForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const username = document.getElementById('login-username').value.trim();
        const password = document.getElementById('login-password').value;
        
        try {
            const res = await fetch('/api/auth/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password })
            });
            
            const data = await res.json();
            
            if (res.ok) {
                state.user = data.user;
                localStorage.setItem('lifegraph_user', JSON.stringify(data.user));
                showAuthAlert("success", `Welcome back, buddy! Logging you in...`);
                setTimeout(() => {
                    showAppWorkspace();
                    clearAuthAlert();
                }, 1000);
            } else {
                showAuthAlert("danger", data.detail || "Invalid username or password");
            }
        } catch (e) {
            showAuthAlert("danger", "Could not connect to API server: " + e.message);
        }
    });
    
    // Sign Up Submission
    regForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const fullname = document.getElementById('reg-fullname').value.trim();
        const username = document.getElementById('reg-username').value.trim();
        const password = document.getElementById('reg-password').value;
        
        try {
            const res = await fetch('/api/auth/register', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password, fullname })
            });
            
            const data = await res.json();
            
            if (res.ok) {
                showAuthAlert("success", "Account registered successfully! Please sign in.");
                setTimeout(() => {
                    tabLogin.click();
                    document.getElementById('login-username').value = username;
                    document.getElementById('login-password').value = '';
                }, 1500);
            } else {
                showAuthAlert("danger", data.detail || "Registration failed. Username may exist.");
            }
        } catch (e) {
            showAuthAlert("danger", "Server request failed: " + e.message);
        }
    });
    
    // Logout Click
    logoutBtn.addEventListener('click', () => {
        logout();
    });
}

function logout() {
    state.user = null;
    localStorage.removeItem('lifegraph_user');
    showAuthScreen();
}

function showAuthScreen() {
    document.getElementById('auth-container').style.display = 'flex';
    document.getElementById('app-container').style.display = 'none';
    
    // Reset forms
    document.getElementById('login-form').reset();
    document.getElementById('register-form').reset();
    clearAuthAlert();
}

function showAppWorkspace() {
    document.getElementById('auth-container').style.display = 'none';
    document.getElementById('app-container').style.display = 'flex';
    
    // Customize user greeting
    if (state.user) {
        document.getElementById('dashboard-welcome-title').textContent = `Welcome, buddy ${state.user.fullname}! 👋`;
        document.getElementById('sidebar-user-tag').textContent = `Buddy: ${state.user.username}`;
        document.getElementById('profile-avatar-letter').textContent = state.user.fullname.charAt(0).toUpperCase();
    }
    
    loadView('dashboard');
}

function showAuthAlert(type, msg) {
    const alertBox = document.getElementById('auth-alert');
    alertBox.className = `auth-alert ${type}`;
    alertBox.textContent = msg;
    alertBox.style.display = 'block';
}

function clearAuthAlert() {
    const alertBox = document.getElementById('auth-alert');
    alertBox.style.display = 'none';
}

// Check Server Connection and update Status Badge
async function checkServerConnection() {
    if (!state.user) return;
    try {
        const res = await apiFetch('/api/settings');
        if (res.ok) {
            document.querySelector('.status-dot').className = 'status-dot connected';
            document.querySelector('.status-text').textContent = 'Server Connected';
            
            // Sync settings from server
            const serverSettings = await res.json();
            if (serverSettings.target_role) {
                state.targetRole = serverSettings.target_role;
                document.getElementById('current-role-badge').textContent = `Target: ${state.targetRole}`;
                const roleSelects = ['career-target-role-select', 'settings-role-select'];
                roleSelects.forEach(id => {
                    const el = document.getElementById(id);
                    if (el) el.value = state.targetRole;
                });
            }
            if (serverSettings.api_key && !state.apiKey) {
                state.apiKey = serverSettings.api_key;
                localStorage.setItem('lifegraph_gemini_key', state.apiKey);
            }
            updateApiKeyBadge();
        }
    } catch (e) {
        console.error("API server connection failed", e);
        document.querySelector('.status-dot').className = 'status-dot disconnected';
        document.querySelector('.status-text').textContent = 'Disconnected';
    }
}

// Update API key badges in UI
function updateApiKeyBadge() {
    const badge = document.getElementById('api-key-warning');
    const keyInput = document.getElementById('settings-api-key-input');
    
    if (state.apiKey && state.apiKey.trim() !== '') {
        badge.className = 'api-key-badge success';
        badge.innerHTML = '<i class="fa-solid fa-circle-check"></i><span>Gemini API Connected</span>';
        if (keyInput) keyInput.value = state.apiKey;
    } else {
        badge.className = 'api-key-badge warning';
        badge.innerHTML = '<i class="fa-solid fa-circle-exclamation"></i><span>No API Key Entered</span>';
        if (keyInput) keyInput.value = '';
    }
}

// Initialize settings state
function initSettings() {
    updateApiKeyBadge();
    document.getElementById('current-role-badge').textContent = `Target: ${state.targetRole}`;
}

// Sidebar Navigation Router
function setupNavigation() {
    const navItems = document.querySelectorAll('.sidebar-nav .nav-item');
    navItems.forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            if (!state.user) return;
            
            navItems.forEach(i => i.classList.remove('active'));
            item.classList.add('active');
            
            const viewName = item.getAttribute('data-view');
            loadView(viewName);
        });
    });
}

// Main View Loader Switchboard
function loadView(viewName) {
    if (!state.user) return;
    state.activeView = viewName;
    
    const sections = document.querySelectorAll('.view-section');
    sections.forEach(s => {
        s.style.display = 'none';
        s.classList.remove('active-view');
    });
    
    hideSearchPanel();
    
    const targetSection = document.getElementById(`view-${viewName}`);
    if (targetSection) {
        targetSection.style.display = 'block';
        targetSection.classList.add('active-view');
    }
    
    switch (viewName) {
        case 'dashboard':
            loadDashboard();
            break;
        case 'knowledge':
            loadVault();
            break;
        case 'chat':
            loadChatView();
            break;
        case 'career':
            loadCareerAndJobs();
            break;
        case 'settings':
            loadSettingsView();
            break;
    }
}

// Formatting helpers
function formatBytes(bytes, decimals = 2) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
}

function formatDate(dateStr) {
    if (!dateStr) return '';
    const date = new Date(dateStr);
    return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
}

function getFileTypeIcon(ext) {
    switch (ext) {
        case 'pdf':
            return '<i class="fa-solid fa-file-pdf" style="color: #ef4444;"></i>';
        case 'docx':
        case 'doc':
            return '<i class="fa-solid fa-file-word" style="color: #3b82f6;"></i>';
        case 'pptx':
        case 'ppt':
            return '<i class="fa-solid fa-file-powerpoint" style="color: #f59e0b;"></i>';
        case 'txt':
            return '<i class="fa-solid fa-file-lines" style="color: #9ca3af;"></i>';
        default:
            return '<i class="fa-solid fa-file" style="color: #6366f1;"></i>';
    }
}

// --- 1. DASHBOARD CONTROLLER ---
async function loadDashboard() {
    if (!state.user) return;
    try {
        const res = await apiFetch('/api/documents');
        state.documents = await res.json();
        
        const skillsRes = await apiFetch('/api/skills');
        state.skills = await skillsRes.json();
        
        const jobsRes = await apiFetch('/api/jobs');
        state.jobs = await jobsRes.json();
        
        document.getElementById('stat-docs-count').textContent = state.documents.length;
        document.getElementById('stat-skills-count').textContent = state.skills.length;
        document.getElementById('stat-jobs-count').textContent = state.jobs.length;
        document.getElementById('stat-queries-count').textContent = state.queriesCount;
        
        renderDashboardSkills();
        renderDashboardRecentDocs();
        renderDashboardJobs();
    } catch (e) {
        console.error("Error loading dashboard data", e);
    }
}

function renderDashboardSkills() {
    const list = document.getElementById('dashboard-skills-list');
    list.innerHTML = '';
    
    const topSkills = [...state.skills].sort((a,b) => b.level - a.level).slice(0, 5);
    
    if (topSkills.length === 0) {
        list.innerHTML = `
            <div class="empty-state">
                <i class="fa-solid fa-circle-nodes"></i>
                <p>No skills detected yet. Upload your Resume/CV inside the Knowledge Vault to map your skills graph.</p>
            </div>
        `;
        return;
    }
    
    topSkills.forEach(s => {
        const item = document.createElement('div');
        item.className = 'skill-bar-item';
        item.innerHTML = `
            <div class="skill-bar-info">
                <span class="skill-bar-name">${s.skill_name} <small style="color: var(--text-muted); font-weight: normal;">(${s.category})</small></span>
                <span class="skill-bar-percent">${s.level}%</span>
            </div>
            <div class="skill-bar-track">
                <div class="skill-bar-fill" style="width: ${s.level}%"></div>
            </div>
        `;
        list.appendChild(item);
    });
}

function renderDashboardRecentDocs() {
    const container = document.getElementById('dashboard-recent-docs');
    container.innerHTML = '';
    
    const recent = state.documents.slice(0, 4);
    
    if (recent.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <i class="fa-solid fa-cloud-arrow-up"></i>
                <p>No study documents uploaded yet.</p>
                <button class="btn btn-primary btn-sm" onclick="document.querySelector('[data-view=knowledge]').click()">Upload First File</button>
            </div>
        `;
        return;
    }
    
    recent.forEach(doc => {
        const item = document.createElement('div');
        item.className = 'recent-doc-item';
        item.innerHTML = `
            <div class="doc-meta-left">
                <div class="doc-type-icon">${getFileTypeIcon(doc.file_type)}</div>
                <div class="doc-info-text">
                    <span class="doc-title-str" title="${doc.filename}">${doc.filename}</span>
                    <span class="doc-size-str">${formatBytes(doc.file_size)} • ${formatDate(doc.uploaded_at)}</span>
                </div>
            </div>
            <div class="doc-actions-right">
                <button class="btn-icon-sm" title="Chat about this document" onclick="quickChat('${doc.id}')"><i class="fa-solid fa-comments"></i></button>
                <button class="btn-icon-sm" title="View document content" onclick="viewDocContent('${doc.id}')"><i class="fa-solid fa-eye"></i></button>
            </div>
        `;
        container.appendChild(item);
    });
}

function renderDashboardJobs() {
    const list = document.getElementById('dashboard-jobs-list');
    list.innerHTML = '';
    
    const topJobs = state.jobs.slice(0, 3);
    
    if (topJobs.length === 0) {
        list.innerHTML = `
            <div class="empty-state" style="grid-column: 1 / -1">
                <i class="fa-solid fa-briefcase"></i>
                <p>No matching jobs found. Save your API key or configure Target Role to load matching vacancies.</p>
            </div>
        `;
        return;
    }
    
    topJobs.forEach(job => {
        const card = document.createElement('div');
        card.className = 'job-card-premium';
        
        const tagSpans = job.tags.slice(0, 3).map(t => `<span class="job-tag">${t}</span>`).join('');
        
        card.innerHTML = `
            <div class="job-card-header">
                <div class="job-role-info">
                    <h4>${job.title}</h4>
                    <span>${job.company}</span>
                </div>
                <div class="job-match-badge">${job.match_score}% Match</div>
            </div>
            <div class="job-meta-row">
                <span><i class="fa-solid fa-location-dot"></i> ${job.location}</span>
            </div>
            <div class="job-tags-list">
                ${tagSpans}
            </div>
            <div class="job-card-footer">
                <span class="job-source-text">via ${job.source}</span>
                <a href="${job.url}" target="_blank" class="btn btn-secondary btn-sm" style="padding: 4px 10px;">Apply <i class="fa-solid fa-arrow-up-right-from-square"></i></a>
            </div>
        `;
        list.appendChild(card);
    });
}

function quickChat(docId) {
    document.querySelector('[data-view=chat]').click();
    const select = document.getElementById('chat-tool-doc-select');
    if (select) {
        select.value = docId;
    }
}

// --- 2. GLOBAL KNOWLEDGE SEARCH CONTROLLER ---
function setupGlobalSearch() {
    const input = document.getElementById('global-search-input');
    const clearBtn = document.getElementById('search-clear-btn');
    const closeBtn = document.getElementById('close-search-panel-btn');
    
    clearBtn.addEventListener('click', () => {
        input.value = '';
        clearBtn.style.display = 'none';
        hideSearchPanel();
    });
    
    closeBtn.addEventListener('click', () => {
        hideSearchPanel();
    });
    
    let debounceTimer;
    input.addEventListener('keyup', (e) => {
        const val = input.value.trim();
        if (val.length > 0) {
            clearBtn.style.display = 'block';
        } else {
            clearBtn.style.display = 'none';
        }
        
        if (e.key === 'Enter') {
            clearTimeout(debounceTimer);
            executeGlobalSearch(val);
        } else {
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(() => {
                if (val.length >= 3) {
                    executeGlobalSearch(val);
                }
            }, 600);
        }
    });
}

function hideSearchPanel() {
    const panel = document.getElementById('search-results-panel');
    panel.style.display = 'none';
}

async function executeGlobalSearch(query) {
    if (!state.user || !query) return;
    
    const panel = document.getElementById('search-results-panel');
    const queryDisplay = document.getElementById('search-query-display');
    const metaText = document.getElementById('search-meta-text');
    const list = document.getElementById('search-results-list');
    
    queryDisplay.textContent = query;
    panel.style.display = 'block';
    list.innerHTML = '<div class="empty-state"><i class="fa-solid fa-spinner fa-spin"></i><p>Scanning document vector memory...</p></div>';
    
    try {
        const res = await apiFetch(`/api/search?q=${encodeURIComponent(query)}`);
        const results = await res.json();
        
        metaText.textContent = `Found ${results.length} matching document sections`;
        list.innerHTML = '';
        
        if (results.length === 0) {
            list.innerHTML = `
                <div class="empty-state">
                    <i class="fa-solid fa-magnifying-glass"></i>
                    <p>No matches found in vector database. Try different keywords.</p>
                </div>
            `;
            return;
        }
        
        results.forEach(res => {
            const card = document.createElement('div');
            card.className = 'search-result-card';
            
            const escapedQuery = query.replace(/[-\/\\^$*+?.()|[\]{}]/g, '\\$&');
            const reg = new RegExp(`(${escapedQuery})`, 'gi');
            const highlightedText = res.text.replace(reg, '<strong style="color: #22d3ee; background-color: rgba(6, 182, 212, 0.15); padding: 0 4px; border-radius: 3px;">$1</strong>');
            
            card.innerHTML = `
                <div class="result-card-header">
                    <span class="result-filename"><i class="fa-solid fa-file-pdf"></i> ${res.filename}</span>
                    <span class="result-match-type">${res.location} • Match: ${Math.round(res.score * 100)}%</span>
                </div>
                <div class="result-snippet">${highlightedText}</div>
                <div class="result-actions">
                    <button onclick="viewDocContent('${res.document_id}')"><i class="fa-solid fa-eye"></i> View Full File</button>
                    <button onclick="quickChat('${res.document_id}')"><i class="fa-solid fa-comments"></i> Ask AI about this</button>
                </div>
            `;
            list.appendChild(card);
        });
        
        panel.scrollIntoView({ behavior: 'smooth' });
    } catch (e) {
        console.error("Search failed", e);
        list.innerHTML = `<div class="empty-state"><i class="fa-solid fa-triangle-exclamation"></i><p>Search failed: ${e.message}</p></div>`;
    }
}

// --- 3. KNOWLEDGE VAULT CONTROLLER (Upload / DB files list) ---
function loadVault() {
    fetchVaultDocuments();
}

async function fetchVaultDocuments() {
    if (!state.user) return;
    try {
        const res = await apiFetch('/api/documents');
        state.documents = await res.json();
        
        document.getElementById('vault-docs-count').textContent = state.documents.length;
        renderVaultTable();
        updateChatDocSelect();
    } catch (e) {
        console.error("Error fetching vault files", e);
    }
}

function renderVaultTable() {
    const tbody = document.getElementById('vault-documents-tbody');
    tbody.innerHTML = '';
    
    if (state.documents.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="6">
                    <div class="empty-state">
                        <i class="fa-solid fa-cloud-arrow-up"></i>
                        <p>No study documents uploaded yet. Drag & Drop files on the left.</p>
                    </div>
                </td>
            </tr>
        `;
        return;
    }
    
    state.documents.forEach(doc => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>
                <div class="doc-meta-left">
                    <div class="doc-type-icon">${getFileTypeIcon(doc.file_type)}</div>
                    <span class="doc-title-str" title="${doc.filename}">${doc.filename}</span>
                </div>
            </td>
            <td><span class="doc-tag">${doc.file_type.toUpperCase()}</span></td>
            <td>${formatBytes(doc.file_size)}</td>
            <td>${formatDate(doc.uploaded_at)}</td>
            <td>
                <div style="display: flex; gap: 4px;">
                    <button class="btn btn-secondary btn-sm" style="padding: 4px 8px;" onclick="runStudyToolFromVault('quiz', '${doc.id}')" title="Generate practice quiz"><i class="fa-solid fa-list-check"></i> Quiz</button>
                    <button class="btn btn-secondary btn-sm" style="padding: 4px 8px;" onclick="runStudyToolFromVault('summary', '${doc.id}')" title="Generate summary"><i class="fa-solid fa-align-left"></i> Summary</button>
                </div>
            </td>
            <td>
                <div class="doc-actions">
                    <button class="btn-icon-sm" title="View Document content" onclick="viewDocContent('${doc.id}')"><i class="fa-solid fa-eye"></i></button>
                    <a href="/api/documents/${doc.id}/download" class="btn-icon-sm" title="Download original file"><i class="fa-solid fa-download"></i></a>
                    <button class="btn-icon-sm delete" title="Delete file" onclick="deleteDocument('${doc.id}')"><i class="fa-solid fa-trash"></i></button>
                </div>
            </td>
        `;
        tbody.appendChild(tr);
    });
}

function updateChatDocSelect() {
    const select = document.getElementById('chat-tool-doc-select');
    if (!select) return;
    
    const activeVal = select.value;
    select.innerHTML = '<option value="">Select Document...</option>';
    
    state.documents.forEach(doc => {
        const opt = document.createElement('option');
        opt.value = doc.id;
        opt.textContent = doc.filename;
        select.appendChild(opt);
    });
    
    select.value = activeVal;
}

// Drag & Drop Setup
function setupDropZone() {
    const dropZone = document.getElementById('drop-zone');
    const fileInput = document.getElementById('file-input');
    
    if (!dropZone) return;
    
    ['dragenter', 'dragover'].forEach(eventName => {
        dropZone.addEventListener(eventName, (e) => {
            e.preventDefault();
            dropZone.classList.add('dragover');
        }, false);
    });
    
    ['dragleave', 'drop'].forEach(eventName => {
        dropZone.addEventListener(eventName, (e) => {
            e.preventDefault();
            dropZone.classList.remove('dragover');
        }, false);
    });
    
    dropZone.addEventListener('drop', (e) => {
        const dt = e.dataTransfer;
        const files = dt.files;
        handleFilesUpload(files);
    });
    
    fileInput.addEventListener('change', () => {
        handleFilesUpload(fileInput.files);
    });
}

// Handles files uploads with session id header injected
async function handleFilesUpload(files) {
    if (!state.user || files.length === 0) return;
    
    const isResume = document.getElementById('is-resume-checkbox').checked;
    const progressContainer = document.getElementById('upload-progress-container');
    const filenameEl = document.getElementById('upload-filename');
    const percentEl = document.getElementById('upload-percent');
    const fillEl = document.getElementById('upload-progress-fill');
    
    progressContainer.style.display = 'block';
    
    for (let i = 0; i < files.length; i++) {
        const file = files[i];
        filenameEl.textContent = `Uploading: ${file.name} (${i+1}/${files.length})`;
        
        try {
            await new Promise((resolve, reject) => {
                const xhr = new XMLHttpRequest();
                const formData = new FormData();
                formData.append('file', file);
                formData.append('is_resume', isResume);
                
                xhr.upload.addEventListener('progress', (e) => {
                    if (e.lengthComputable) {
                        const pct = Math.round((e.loaded / e.total) * 100);
                        percentEl.textContent = `${pct}%`;
                        fillEl.style.width = `${pct}%`;
                    }
                });
                
                xhr.addEventListener('load', () => {
                    if (xhr.status >= 200 && xhr.status < 300) {
                        resolve(JSON.parse(xhr.responseText));
                    } else if (xhr.status === 401) {
                        logout();
                        reject(new Error("Session expired. Please sign in again."));
                    } else {
                        reject(new Error(`Upload failed: ${xhr.statusText}`));
                    }
                });
                
                xhr.addEventListener('error', () => reject(new Error('Network error during upload')));
                
                xhr.open('POST', '/api/upload');
                
                // Inject authentication header
                xhr.setRequestHeader('X-User-Id', String(state.user.id));
                xhr.send(formData);
            });
        } catch (e) {
            console.error(`Upload error for file ${file.name}`, e);
            alert(`Error uploading file ${file.name}: ${e.message}`);
        }
    }
    
    percentEl.textContent = '100%';
    fillEl.style.width = '100%';
    setTimeout(() => {
        progressContainer.style.display = 'none';
        document.getElementById('is-resume-checkbox').checked = false;
        fetchVaultDocuments();
    }, 1000);
}

// Delete document
async function deleteDocument(docId) {
    if (!state.user) return;
    if (!confirm('Are you sure you want to delete this document from your database? This deletes all associated vector study memory!')) return;
    
    try {
        const res = await apiFetch(`/api/documents/${docId}`, { method: 'DELETE' });
        if (res.ok) {
            fetchVaultDocuments();
        } else {
            const data = await res.json();
            alert(`Error deleting document: ${data.detail}`);
        }
    } catch (e) {
        console.error("Delete document request error", e);
    }
}

// --- 4. DOCUMENT VIEWER MODAL CONTROLLER ---
function setupDocumentViewer() {
    const modal = document.getElementById('document-viewer-modal');
    const closeBtn = document.getElementById('close-viewer-modal-btn');
    const closeBtn2 = document.getElementById('close-viewer-modal-btn2');
    
    const closeModal = () => { modal.style.display = 'none'; };
    if (closeBtn) closeBtn.addEventListener('click', closeModal);
    if (closeBtn2) closeBtn2.addEventListener('click', closeModal);
}

async function viewDocContent(docId) {
    if (!state.user) return;
    const modal = document.getElementById('document-viewer-modal');
    const titleEl = document.getElementById('modal-doc-title');
    const contentEl = document.getElementById('modal-doc-content');
    const dlBtn = document.getElementById('modal-download-btn');
    
    modal.style.display = 'flex';
    titleEl.textContent = 'Retrieving Document text...';
    contentEl.textContent = 'Loading text extract from SQLite...';
    
    try {
        const res = await apiFetch(`/api/documents`);
        const docs = await res.json();
        const doc = docs.find(d => String(d.id) === String(docId));
        
        if (!doc) {
            titleEl.textContent = 'File Not Found';
            contentEl.textContent = 'The document record could not be loaded.';
            return;
        }
        
        titleEl.textContent = doc.filename;
        dlBtn.onclick = () => { window.location.href = `/api/documents/${docId}/download`; };
        
        // Fetch document search results with empty query (API lists all chunks)
        const chunksRes = await apiFetch(`/api/search?q=`);
        const searchMatches = await chunksRes.json();
        
        const docMatches = searchMatches.filter(m => String(m.document_id) === String(docId));
        
        if (docMatches.length > 0) {
            docMatches.sort((a,b) => a.chunk_id - b.chunk_id);
            const fullText = docMatches.map(m => `--- ${m.location} ---\n${m.text}`).join('\n\n');
            contentEl.textContent = fullText;
        } else {
            contentEl.textContent = "Raw text extraction is empty or not indexed yet. Try searching for this file.";
        }
        
    } catch (e) {
        console.error("Error viewing document contents", e);
        contentEl.textContent = `Error loading document contents: ${e.message}`;
    }
}

// --- 5. AI STUDY CHAT CONTROLLER (RAG) ---
function loadChatView() {
    updateChatDocSelect();
    document.getElementById('chat-connected-docs-text').textContent = `Ask anything about your ${state.documents.length} uploaded documents`;
}

function setupChat() {
    const sendBtn = document.getElementById('chat-send-btn');
    const input = document.getElementById('chat-input-field');
    const messagesArea = document.getElementById('chat-messages-area');
    
    if (!sendBtn) return;
    
    sendBtn.addEventListener('click', () => {
        submitChatQuery();
    });
    
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            submitChatQuery();
        }
    });
    
    const suggCards = document.querySelectorAll('.suggestion-card');
    suggCards.forEach(card => {
        card.addEventListener('click', () => {
            const prompt = card.getAttribute('data-prompt');
            input.value = prompt;
            submitChatQuery();
        });
    });
    
    document.getElementById('chat-tool-quiz-btn').addEventListener('click', () => runStudyTool('quiz'));
    document.getElementById('chat-tool-sum-btn').addEventListener('click', () => runStudyTool('summary'));
    document.getElementById('chat-tool-exp-btn').addEventListener('click', () => runStudyTool('explain'));
}

function formatMessageMarkdown(text) {
    if (!text) return '';
    let formatted = text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
        
    formatted = formatted.replace(/```(.*?)\n([\s\S]*?)```/g, '<pre><code class="language-$1">$2</code></pre>');
    formatted = formatted.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    formatted = formatted.replace(/`(.*?)`/g, '<code>$1</code>');
    formatted = formatted.replace(/^\s*-\s+(.*?)$/gm, '<li>$1</li>');
    formatted = formatted.replace(/(<li>.*?<\/li>)/gs, '<ul>$1</ul>');
    formatted = formatted.replace(/<\/ul>\s*<ul>/g, '');
    formatted = formatted.replace(/\n/g, '<br>');
    
    return formatted;
}

function appendChatMessage(sender, text, isWelcomeRemove = true) {
    const messagesArea = document.getElementById('chat-messages-area');
    
    if (isWelcomeRemove) {
        const welcome = messagesArea.querySelector('.chat-welcome-state');
        if (welcome) welcome.remove();
    }
    
    const bubble = document.createElement('div');
    bubble.className = `chat-msg-bubble ${sender}`;
    
    const avatarIcon = sender === 'user' ? '<i class="fa-solid fa-user"></i>' : '<i class="fa-solid fa-robot"></i>';
    
    bubble.innerHTML = `
        <div class="bubble-avatar">${avatarIcon}</div>
        <div class="bubble-content">
            ${sender === 'bot' ? formatMessageMarkdown(text) : `<p>${text}</p>`}
        </div>
    `;
    
    messagesArea.appendChild(bubble);
    messagesArea.scrollTop = messagesArea.scrollHeight;
    return bubble;
}

async function submitChatQuery() {
    if (!state.user) return;
    const input = document.getElementById('chat-input-field');
    const query = input.value.trim();
    if (!query) return;
    
    input.value = '';
    appendChatMessage('user', query);
    const loadingBubble = appendChatMessage('bot', '<i class="fa-solid fa-ellipsis fa-bounce"></i> Searching vector database & writing response...');
    
    try {
        const res = await apiFetch('/api/chat', {
            method: 'POST',
            body: JSON.stringify({ query: query })
        });
        
        const data = await res.json();
        loadingBubble.remove();
        appendChatMessage('bot', data.answer);
        
        state.queriesCount++;
        localStorage.setItem('lifegraph_queries_count', state.queriesCount);
        renderChatSources(data.sources);
    } catch (e) {
        console.error("Chat API error", e);
        loadingBubble.remove();
        appendChatMessage('bot', `Could not connect to AI endpoint: ${e.message}`);
    }
}

function renderChatSources(sources) {
    const container = document.getElementById('chat-sources-list');
    container.innerHTML = '';
    
    if (!sources || sources.length === 0) {
        container.innerHTML = `
            <div class="sources-empty-state">
                <i class="fa-regular fa-folder-open"></i>
                <p>Answers are supported by document extracts shown here.</p>
            </div>
        `;
        return;
    }
    
    sources.forEach(src => {
        const card = document.createElement('div');
        card.className = 'source-item-card';
        card.innerHTML = `
            <div class="source-title-bar">
                <span class="source-filename" title="${src.filename}"><i class="fa-solid fa-file-lines"></i> ${src.filename}</span>
                <span class="source-location">${src.location}</span>
            </div>
            <div class="source-text-extract">"${src.text}"</div>
        `;
        container.appendChild(card);
    });
}

async function runStudyTool(toolType) {
    if (!state.user) return;
    const docSelect = document.getElementById('chat-tool-doc-select');
    const docId = docSelect.value;
    
    if (!docId) {
        alert("Please select a document first to use the study tools.");
        return;
    }
    
    const docName = docSelect.options[docSelect.selectedIndex].text;
    
    let label = "";
    if (toolType === 'quiz') label = `Create a 5-question multiple choice study quiz for: **${docName}**`;
    else if (toolType === 'summary') label = `Summarize key learning concepts from: **${docName}**`;
    else if (toolType === 'explain') label = `Explain the top 5 complex terms inside: **${docName}**`;
    
    appendChatMessage('user', label);
    const loadingBubble = appendChatMessage('bot', `<i class="fa-solid fa-spinner fa-spin"></i> Triggering AI Study tools pipeline for ${docName}... This may take 15-30 seconds.`);
    
    try {
        const res = await apiFetch('/api/chat/study-tool', {
            method: 'POST',
            body: JSON.stringify({ tool_type: toolType, document_id: parseInt(docId) })
        });
        
        const data = await res.json();
        loadingBubble.remove();
        appendChatMessage('bot', data.result);
        
        state.queriesCount++;
        localStorage.setItem('lifegraph_queries_count', state.queriesCount);
    } catch (e) {
        console.error("Study tool error", e);
        loadingBubble.remove();
        appendChatMessage('bot', `Failed to run study tool: ${e.message}`);
    }
}

function runStudyToolFromVault(toolType, docId) {
    document.querySelector('[data-view=chat]').click();
    const docSelect = document.getElementById('chat-tool-doc-select');
    if (docSelect) {
        docSelect.value = docId;
        setTimeout(() => {
            runStudyTool(toolType);
        }, 500);
    }
}

// --- 6. CAREER & JOBS CONTROLLER ---
function setupCareer() {
    const roleSelect = document.getElementById('career-target-role-select');
    roleSelect.addEventListener('change', () => {
        state.targetRole = roleSelect.value;
        document.getElementById('current-role-badge').textContent = `Target: ${state.targetRole}`;
        saveTargetRoleSetting(state.targetRole);
    });
    
    document.getElementById('jobs-refresh-btn').addEventListener('click', () => {
        loadCareerAndJobs(true);
    });
}

async function saveTargetRoleSetting(role) {
    if (!state.user) return;
    try {
        await apiFetch('/api/settings', {
            method: 'POST',
            body: JSON.stringify({ target_role: role })
        });
        loadCareerAndJobs();
    } catch (e) {
        console.error("Error saving career setting", e);
    }
}

async function loadCareerAndJobs(forceRefresh = false) {
    if (!state.user) return;
    const skillsList = document.getElementById('career-skills-level-list');
    const jobsList = document.getElementById('career-jobs-list-container');
    const acquiredUl = document.getElementById('gap-acquired-ul');
    const missingUl = document.getElementById('gap-missing-ul');
    const recommendationsList = document.getElementById('gap-recommendations-list');
    
    skillsList.innerHTML = '<div class="empty-state"><i class="fa-solid fa-spinner fa-spin"></i><p>Loading skills graph...</p></div>';
    jobsList.innerHTML = '<div class="empty-state"><i class="fa-solid fa-spinner fa-spin"></i><p>Scanning job feeds...</p></div>';
    
    try {
        const skillsRes = await apiFetch('/api/skills');
        state.skills = await skillsRes.json();
        
        const jobsRes = await apiFetch('/api/jobs');
        state.jobs = await jobsRes.json();
        
        const gapRes = await apiFetch('/api/jobs/gap');
        const gapData = await gapRes.json();
        
        renderDetailedSkillsList(skillsList);
        
        document.getElementById('gap-role-title').textContent = state.targetRole;
        document.getElementById('skills-acquired-count').textContent = gapData.skills_acquired.length;
        document.getElementById('skills-gap-count').textContent = gapData.skills_gap.length;
        
        acquiredUl.innerHTML = gapData.skills_acquired.map(s => `<li><i class="fa-solid fa-circle-check"></i> ${s}</li>`).join('') || '<li>No matching skills detected.</li>';
        missingUl.innerHTML = gapData.skills_gap.map(s => `<li><i class="fa-solid fa-triangle-exclamation"></i> ${s}</li>`).join('') || '<li>No skill gaps! You are a perfect fit.</li>';
        
        recommendationsList.innerHTML = '';
        if (gapData.recommendations.length === 0) {
            recommendationsList.innerHTML = '<p style="font-size: 13px; color: var(--text-muted);">No recommendations needed.</p>';
        } else {
            gapData.recommendations.forEach(rec => {
                const card = document.createElement('div');
                card.className = 'rec-card';
                card.innerHTML = `
                    <span class="rec-topic">${rec.topic}</span>
                    <span class="rec-resource"><i class="fa-solid fa-book"></i> Recommended: ${rec.resource}</span>
                `;
                recommendationsList.appendChild(card);
            });
        }
        
        renderDetailedJobsList(jobsList);
    } catch (e) {
        console.error("Error loading career data", e);
    }
}

function renderDetailedSkillsList(container) {
    container.innerHTML = '';
    
    if (state.skills.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <i class="fa-solid fa-chart-pie"></i>
                <p>No skills detected yet. Upload your Resume/CV inside the Knowledge Vault.</p>
            </div>
        `;
        return;
    }
    
    state.skills.forEach(s => {
        const row = document.createElement('div');
        row.className = 'career-skill-row';
        
        row.innerHTML = `
            <div class="c-skill-left">
                <span class="c-skill-name">${s.skill_name}</span>
                <span class="c-skill-cat">${s.category}</span>
            </div>
            <div class="c-skill-center">
                <div class="skill-bar-track" style="flex-grow: 1; height: 6px;">
                    <div class="skill-bar-fill" style="width: ${s.level}%; height: 100%;"></div>
                </div>
                <span class="skill-bar-percent" style="font-size: 12px; font-weight: 700; width: 35px; text-align: right;">${s.level}%</span>
            </div>
            <div class="c-skill-right" title="${s.evidence || ''}">${s.evidence || 'Self-assessed profile strength'}</div>
        `;
        container.appendChild(row);
    });
}

function renderDetailedJobsList(container) {
    container.innerHTML = '';
    
    if (state.jobs.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <i class="fa-solid fa-briefcase"></i>
                <p>No job listings found. Make sure your target role matches remote vacancies.</p>
            </div>
        `;
        return;
    }
    
    state.jobs.forEach(job => {
        const card = document.createElement('div');
        card.className = 'job-card-detailed';
        
        const matchedSpans = job.matched_skills.map(s => `<span class="eval-badge match">${s}</span>`).join('') || '<span class="eval-badge" style="color: var(--text-muted)">None</span>';
        const gapSpans = job.missing_skills.map(s => `<span class="eval-badge gap">${s}</span>`).join('') || '<span class="eval-badge" style="color: var(--text-muted)">None</span>';
        
        card.innerHTML = `
            <div class="job-detailed-top">
                <div class="job-company-block">
                    <h4>${job.title}</h4>
                    <div class="job-company-name">${job.company} • ${job.location}</div>
                </div>
                <div class="job-match-radial-container">
                    <span class="match-gradient-text">${job.match_score}%</span>
                    <span class="match-subtext">Match Score</span>
                </div>
            </div>
            
            <div class="job-desc-extract">
                ${job.description.length > 220 ? job.description.slice(0, 220) + "..." : job.description}
            </div>
            
            <div class="job-skills-match-evaluation">
                <div class="eval-row">
                    <span class="eval-label">Skills Match:</span>
                    <div class="eval-badges">${matchedSpans}</div>
                </div>
                <div class="eval-row">
                    <span class="eval-label">Skills Gap:</span>
                    <div class="eval-badges">${gapSpans}</div>
                </div>
            </div>
            
            <div class="job-card-footer" style="margin-top: 0; padding-top: 14px;">
                <span class="job-source-text">Feed: ${job.source}</span>
                <a href="${job.url}" target="_blank" class="btn btn-primary btn-sm">Inspect Role & Apply <i class="fa-solid fa-arrow-up-right-from-square"></i></a>
            </div>
        `;
        container.appendChild(card);
    });
}

// --- 7. SETTINGS CONTROLLER ---
function loadSettingsView() {
    updateApiKeyBadge();
}

function setupSettingsPage() {
    const saveBtn = document.getElementById('save-settings-btn');
    const keyInput = document.getElementById('settings-api-key-input');
    const toggleBtn = document.getElementById('toggle-key-visibility-btn');
    const roleSelect = document.getElementById('settings-role-select');
    
    toggleBtn.addEventListener('click', () => {
        const type = keyInput.type === 'password' ? 'text' : 'password';
        keyInput.type = type;
        toggleBtn.innerHTML = type === 'password' ? '<i class="fa-solid fa-eye"></i>' : '<i class="fa-solid fa-eye-slash"></i>';
    });
    
    saveBtn.addEventListener('click', async () => {
        const key = keyInput.value.trim();
        const role = roleSelect.value;
        
        state.apiKey = key;
        state.targetRole = role;
        localStorage.setItem('lifegraph_gemini_key', key);
        document.getElementById('current-role-badge').textContent = `Target: ${state.targetRole}`;
        
        try {
            const res = await apiFetch('/api/settings', {
                method: 'POST',
                body: JSON.stringify({
                    api_key: key,
                    target_role: role
                })
            });
            if (res.ok) {
                alert("Settings configured successfully!");
                updateApiKeyBadge();
                checkServerConnection();
            }
        } catch (e) {
            console.error("Save settings API call failed", e);
            alert("Settings saved locally but server failed to update: " + e.message);
        }
    });
    
    document.getElementById('clear-skills-btn').addEventListener('click', async () => {
        if (!state.user) return;
        if (!confirm("Reset your extracted student skills? This will restore dummy skills until a resume is re-uploaded.")) return;
        try {
            const res = await apiFetch('/api/skills/clear', { method: 'POST' });
            if (res.ok) {
                alert("Skills profile cleared.");
                loadDashboard();
            }
        } catch (e) {
            console.error(e);
        }
    });
    
    document.getElementById('factory-reset-btn').addEventListener('click', async () => {
        if (!state.user) return;
        if (!confirm("WARNING: This will delete ALL your uploaded study documents, clear your vector index files, reset skills database tables, and restart your Life Graph environment. Proceed?")) return;
        
        try {
            const res = await apiFetch('/api/documents');
            const docs = await res.json();
            for (const d of docs) {
                await apiFetch(`/api/documents/${d.id}`, { method: 'DELETE' });
            }
            await apiFetch('/api/skills/clear', { method: 'POST' });
            
            alert("Database environment reset complete.");
            loadView('dashboard');
        } catch (e) {
            console.error("Database reset error", e);
            alert("Factory reset failed: " + e.message);
        }
    });
}
