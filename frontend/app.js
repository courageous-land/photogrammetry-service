/**
 * Photogrammetry Service - Frontend
 */

class PhotogrammetryApp {
    constructor() {
        this.apiUrl = window.PHOTOGRAMMETRY_CONFIG?.API_URL || '';
        this.projects = [];
        
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
        const opts = { method, headers: { 'Content-Type': 'application/json' } };
        if (body) opts.body = JSON.stringify(body);
        const res = await fetch(`${this.apiUrl}${path}`, opts);
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
            this.projectsList.innerHTML = `<p class="empty">Erro: ${err.message}</p>`;
        }
    }

    renderList() {
        if (this.projects.length === 0) {
            this.projectsList.innerHTML = '<p class="empty">Nenhum projeto. Clique em "Novo Projeto" para criar.</p>';
            return;
        }
        
        this.projectsList.innerHTML = this.projects.map(p => `
            <div class="project-item" onclick="app.openProject('${p.project_id}')">
                <div class="project-info">
                    <div class="project-name">${this.esc(p.name || 'Sem nome')}</div>
                    <div class="project-meta">
                        <span>${p.files_count || 0} arquivos</span>
                        <span>${p.progress || 0}%</span>
                        <span>${this.formatDate(p.created_at)}</span>
                    </div>
                </div>
                <span class="status status-${p.status}">${this.statusLabel(p.status)}</span>
            </div>
        `).join('');
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
        let html = `<div class="status-box info">
            <strong>Status:</strong> ${this.statusLabel(p.status)} | 
            <strong>Arquivos:</strong> ${p.files_count || 0} | 
            <strong>Progresso:</strong> ${p.progress || 0}%
        </div>`;

        // Upload
        if (['created', 'pending'].includes(p.status)) {
            html += `
                <div class="section">
                    <div class="section-title">UPLOAD DE IMAGENS</div>
                    <input type="file" id="files" multiple accept=".jpg,.jpeg,.png,.tif,.tiff">
                    <button class="btn" style="margin-top:12px" onclick="app.upload('${p.project_id}')">Enviar</button>
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
                        <button class="btn btn-primary" onclick="app.process('${p.project_id}')">Iniciar</button>
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
                    <button class="btn" style="margin-top:12px" onclick="app.openProject('${p.project_id}')">Atualizar</button>
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
                            const safeUrl = (url && url.startsWith('https://')) ? url : '#';
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
            if (container) container.innerHTML = `<p style="color:#991b1b">Erro: ${err.message}</p>`;
        }
    }

    async upload(id) {
        const files = Array.from(document.getElementById('files').files);
        const msg = document.getElementById('uploadMsg');
        if (!files.length) return alert('Selecione arquivos');
        
        msg.innerHTML = '<div class="status-box info">Enviando...</div>';
        
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
            msg.innerHTML = `<div class="status-box error">Erro: ${err.message}</div>`;
        }
    }

    async process(id) {
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
        }
    }

    esc(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
    formatDate(d) { return d ? new Date(d).toLocaleDateString('pt-BR') : '-'; }
}

const app = new PhotogrammetryApp();
