/**
 * Photogrammetry Service - Frontend
 */

class PhotogrammetryApp {
    constructor() {
        this.apiUrl = window.PHOTOGRAMMETRY_CONFIG?.API_URL || '';
        this.projects = [];
        this.isUploading = false;
        this.isProcessing = false;
        
        this.init();
    }

    init() {
        this.modal = document.getElementById('modal');
        this.modalTitle = document.getElementById('modalTitle');
        this.modalBody = document.getElementById('modalBody');
        this.projectsList = document.getElementById('projectsList');
        
        document.getElementById('newProjectBtn').onclick = () => this.showNewProjectModal();
        document.getElementById('modalClose').onclick = () => this.closeModal();
        this.modal.onclick = (e) => { if (e.target === this.modal) this.closeModal(); };
        
        this.loadProjects();
        setInterval(() => this.pollUpdates(), 10000);
    }

    async api(method, path, body = null) {
        const isIap = this.apiUrl.includes('courageousland.com');
        const opts = {
            method,
            headers: { 'Content-Type': 'application/json' },
            ...(isIap && { credentials: 'include' })
        };
        if (body) opts.body = JSON.stringify(body);
        const res = await fetch(`${this.apiUrl}${path}`, opts);
        if (res.status === 401 || res.status === 403) {
            throw new Error('Sessao expirada ou sem permissao. Faca login novamente.');
        }
        if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || 'Erro');
        return res.json();
    }

    async loadProjects() {
        try {
            // API retorna lista direta, nao { projects: [...] }
            const data = await this.api('GET', '/projects');
            this.projects = Array.isArray(data) ? data : [];
            this.renderList();
        } catch (err) {
            this.projectsList.innerHTML = `<p class="empty">Erro: ${this.esc(err.message)}</p>`;
        }
    }

    renderList() {
        if (this.projects.length === 0) {
            this.projectsList.innerHTML = '<p class="empty">Nenhum projeto. Clique em "Novo Projeto" para criar.</p>';
            return;
        }
        
        this.projectsList.innerHTML = this.projects.map(p => {
            const safeId = this.safeProjectId(p.project_id);
            const safeStatus = this.safeStatusClass(p.status);
            const onclick = safeId ? ` onclick="app.openProject('${safeId}')"` : '';
            return `
            <div class="project-item"${onclick}>
                <div class="project-info">
                    <div class="project-name">${this.esc(p.name || 'Sem nome')}</div>
                    <div class="project-meta">
                        <span>${p.files_count || 0} arquivos</span>
                        <span>${p.progress || 0}%</span>
                        <span>${this.formatDate(p.created_at)}</span>
                    </div>
                </div>
                <span class="status status-${safeStatus}">${this.statusLabel(safeStatus)}</span>
            </div>
        `;
        }).join('');
    }

    statusLabel(status) {
        const labels = {
            created: 'Criado',
            pending: 'Aguardando',
            processing: 'Processando',
            completed: 'Concluido',
            failed: 'Falhou'
        };
        return labels[status] || status;
    }

    async pollUpdates() {
        if (this.projects.some(p => p.status === 'processing')) {
            await this.loadProjects();
        }
    }

    openModal(title, content) {
        this.modalTitle.textContent = title;
        this.modalBody.innerHTML = content;
        this.modal.classList.remove('hidden');
    }

    closeModal() {
        this.modal.classList.add('hidden');
    }

    showNewProjectModal() {
        this.openModal('Novo Projeto', `
            <div class="form-group">
                <label>Nome do Projeto</label>
                <input type="text" id="inputName" placeholder="Ex: Fazenda Norte">
            </div>
            <div class="form-actions">
                <button class="btn btn-primary" onclick="app.createProject()">Criar</button>
                <button class="btn" onclick="app.closeModal()">Cancelar</button>
            </div>
        `);
        document.getElementById('inputName').focus();
    }

    async createProject() {
        const name = document.getElementById('inputName').value.trim() || `Projeto ${Date.now()}`;
        try {
            // API retorna { project_id, name, status, created_at }
            const data = await this.api('POST', '/projects', { name });
            await this.loadProjects();
            this.openProject(data.project_id);
        } catch (err) {
            alert('Erro: ' + err.message);
        }
    }

    async openProject(id) {
        try {
            const p = await this.api('GET', `/projects/${id}`);
            this.showProjectModal(p);
        } catch (err) {
            alert('Erro: ' + err.message);
        }
    }

    showProjectModal(p) {
        const safeId = this.safeProjectId(p.project_id);
        let html = `<div class="status-box info">
            <strong>Status:</strong> ${this.statusLabel(p.status)} | 
            <strong>Arquivos:</strong> ${p.files_count || 0} | 
            <strong>Progresso:</strong> ${p.progress || 0}%
        </div>`;
        if (!safeId) {
            html += `<div class="section"><div class="status-box error">ID de projeto invalido.</div></div>`;
            this.openModal(p.name || 'Projeto', html);
            return;
        }

        // Upload
        if (['created', 'pending'].includes(p.status)) {
            html += `
                <div class="section">
                    <div class="section-title">UPLOAD DE IMAGENS</div>
                    <input type="file" id="files" multiple accept=".jpg,.jpeg,.png,.tif,.tiff">
                    <button class="btn" style="margin-top:12px" onclick="app.upload('${safeId}')">Enviar</button>
                    <div id="uploadMsg"></div>
                </div>
            `;
        }

        // Process
        if (p.status === 'pending') {
            const canProcess = (p.files_count || 0) >= 3;
            html += `
                <div class="section">
                    <div class="section-title">PROCESSAMENTO</div>
                    ${canProcess ? `
                        <div class="form-row">
                            <div class="form-group">
                                <label>Qualidade</label>
                                <select id="optQuality">
                                    <option value="low">Rapida</option>
                                    <option value="medium" selected>Padrao</option>
                                    <option value="high">Maxima</option>
                                </select>
                            </div>
                            <div class="form-group">
                                <label>Opcoes</label>
                                <label class="checkbox-label"><input type="checkbox" id="optDtm"> DTM</label>
                                <label class="checkbox-label"><input type="checkbox" id="optMulti"> Multiespectral</label>
                            </div>
                        </div>
                        <button class="btn btn-primary" onclick="app.process('${safeId}')">Iniciar</button>
                    ` : `<p style="color:#666">Envie ao menos 3 imagens.</p>`}
                </div>
            `;
        }

        // Processing
        if (p.status === 'processing') {
            html += `
                <div class="section">
                    <div class="section-title">PROCESSANDO</div>
                    <div class="progress-bar"><div class="progress-fill" style="width:${p.progress||0}%"></div></div>
                    <p style="font-size:13px;color:#666;margin-top:8px">${p.progress||0}% concluido</p>
                    <button class="btn" style="margin-top:12px" onclick="app.openProject('${safeId}')">Atualizar</button>
                </div>
            `;
            // Auto-refresh every 5 seconds when processing
            setTimeout(() => {
                if (document.getElementById('modal') && !document.getElementById('modal').classList.contains('hidden')) {
                    this.openProject(p.project_id);
                }
            }, 5000);
        }

        // Results - buscar resultados separadamente
        if (p.status === 'completed') {
            html += `
                <div class="section">
                    <div class="section-title">RESULTADOS</div>
                    <div id="resultsContainer">Carregando resultados...</div>
                </div>
            `;
            // Buscar resultados async
            this.loadResults(p.project_id);
        }

        // Error
        if (p.status === 'failed' && p.error_message) {
            html += `<div class="section"><div class="status-box error">${this.esc(p.error_message)}</div></div>`;
        }

        this.openModal(p.name || 'Projeto', html);
    }

    async loadResults(projectId) {
        try {
            const result = await this.api('GET', `/projects/${projectId}/result`);
            const container = document.getElementById('resultsContainer');
            if (!container) return;
            
            if (result.download_urls && result.download_urls.length > 0) {
                container.innerHTML = `
                    <div class="results-list">
                        ${result.download_urls.map((url, i) => {
                            // Sanitize URL - only allow https:// URLs
                            const safeUrl = (url && /^https:\/\/storage\.googleapis\.com\//.test(url)) ? url : '#';
                            return `
                            <div class="result-item">
                                <span>Arquivo ${i + 1}</span>
                                <a href="${safeUrl}" target="_blank" rel="noopener noreferrer">Download</a>
                            </div>`;
                        }).join('')}
                    </div>
                `;
            } else {
                container.innerHTML = '<p style="color:#666">Nenhum resultado disponivel.</p>';
            }
        } catch (err) {
            const container = document.getElementById('resultsContainer');
            if (container) container.innerHTML = `<p style="color:#991b1b">Erro: ${this.esc(err.message)}</p>`;
        }
    }

    async upload(id) {
        if (this.isUploading) return;
        const files = Array.from(document.getElementById('files').files);
        const msg = document.getElementById('uploadMsg');
        if (!files.length) return alert('Selecione arquivos');
        const maxBytes = 100 * 1024 * 1024; // 100MB por arquivo
        const allowedTypes = new Set(['image/jpeg', 'image/png', 'image/tiff', 'image/gif', 'image/webp']);
        for (const file of files) {
            const normalizedType = (file.type || 'application/octet-stream').toLowerCase();
            if (!allowedTypes.has(normalizedType)) {
                return alert(`Tipo de arquivo nao permitido: ${file.name}`);
            }
            if (file.size > maxBytes) {
                return alert(`Arquivo muito grande (max 100MB): ${file.name}`);
            }
        }
        
        msg.innerHTML = '<div class="status-box info">Enviando...</div>';
        this.isUploading = true;
        
        try {
            for (let i = 0; i < files.length; i++) {
                const f = files[i];
                // Endpoint correto: /projects/{id}/upload-url
                const urlData = await this.api('POST', `/projects/${id}/upload-url`, {
                    filename: f.name,
                    content_type: f.type || 'image/jpeg',
                    file_size: f.size,
                    resumable: true
                });
                
                // Upload direto para GCS
                await fetch(urlData.upload_url, {
                    method: 'PUT',
                    headers: { 'Content-Type': f.type || 'application/octet-stream' },
                    body: f
                });
                
                msg.innerHTML = `<div class="status-box info">Enviando ${i+1}/${files.length}...</div>`;
            }
            
            // Finalizar upload
            await this.api('POST', `/projects/${id}/finalize-upload`);
            
            msg.innerHTML = '<div class="status-box success">Concluido!</div>';
            await this.loadProjects();
            
            setTimeout(() => this.openProject(id), 500);
        } catch (err) {
            msg.innerHTML = `<div class="status-box error">Erro: ${this.esc(err.message)}</div>`;
        } finally {
            this.isUploading = false;
        }
    }

    async process(id) {
        if (this.isProcessing) return;
        this.isProcessing = true;
        try {
            await this.api('POST', `/projects/${id}/process`, {
                options: {
                    ortho_quality: document.getElementById('optQuality').value,
                    generate_dtm: document.getElementById('optDtm').checked,
                    multispectral: document.getElementById('optMulti').checked
                }
            });
            await this.loadProjects();
            this.openProject(id);
        } catch (err) {
            alert('Erro: ' + err.message);
        } finally {
            this.isProcessing = false;
        }
    }

    safeProjectId(id) {
        if (typeof id !== 'string') return '';
        return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id) ? id : '';
    }
    safeStatusClass(status) {
        const allowed = new Set(['created', 'pending', 'processing', 'completed', 'failed']);
        return allowed.has(status) ? status : 'created';
    }
    esc(s) { const d = document.createElement('div'); d.textContent = String(s ?? ''); return d.innerHTML; }
    formatDate(d) { return d ? new Date(d).toLocaleDateString('pt-BR') : '-'; }
}

const app = new PhotogrammetryApp();
