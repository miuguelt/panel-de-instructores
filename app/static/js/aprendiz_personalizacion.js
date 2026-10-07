/* Preferencias privadas del aprendiz, confirmadas por la base de datos. */
'use strict';

function initLearnerPersonalization(doc = document, win = window, config) {
    const page = doc.getElementById('panel-aprendiz-root');
    const modal = doc.getElementById('personalizacion-modal');
    const configElement = doc.getElementById('learner-personalization-config');
    if (!page || !modal || (!config && !configElement)) return null;
    config = config || JSON.parse(configElement.textContent);
    const byId = id => doc.getElementById(id);
    const fields = {
        alias: byId('customizer-alias-input'), motto: byId('customizer-motto-input'),
        background: byId('customizer-background-input'), viewMode: byId('customizer-view-mode-input'),
    };
    const saveButton = byId('btn-save-personalizacion');
    const retryButton = byId('personalizacion-retry');
    const reloadButton = byId('personalizacion-reload');
    const legacyButton = byId('personalizacion-legacy');
    const photoInput = byId('customizer-photo-input');
    const orderList = byId('personalizacion-order-list');
    const legacyKey = 'sena_learner_prefs_' + config.learnerId;
    const themes = { sena: '#39a900', indigo: '#2563eb', cyan: '#0891b2', purple: '#7c3aed', amber: '#d97706', emerald: '#059669', rose: '#e11d48', slate: '#475569' };
    const avatars = ['💻', '🚀', '⚡', '🎯', '🧠', '🎨', '🔬', '🦊', '🦁', '🦉', '🌟', '💡', '🛡️', '⚙️', '📚', '🏆'];
    const labels = { 'seccion-progreso': 'Progreso', 'seccion-portafolio-digital': 'Portafolio digital', 'seccion-grupo-trabajo': 'Mi grupo', 'seccion-juicios': 'Juicios de evaluación', 'seccion-aseo': 'Aseo', 'seccion-curva-rendimiento': 'Curva de rendimiento', 'seccion-ranking': 'Mi posición', 'seccion-liga-grupos': 'Liga de grupos', 'seccion-tareas': 'Evidencias' };
    const sections = new Map();
    for (const id of Object.keys(labels)) {
        let section = byId(id);
        if (!section) continue;
        while (section.parentElement && section.parentElement !== page) section = section.parentElement;
        if (section.parentElement === page) sections.set(id, section);
    }
    const defaultOrder = [];
    for (const child of Array.from(page.children)) {
        for (const [id, section] of sections) if (section === child) defaultOrder.push(id);
    }
    const slots = [];
    for (const id of defaultOrder) {
        const marker = doc.createComment('Posición de tarjeta personalizable');
        page.insertBefore(marker, sections.get(id));
        slots.push(marker);
    }
    const defaults = { avatar: '💻', accent: '#39a900', themeName: 'sena', motto: '', alias: '', background: 'plain', sectionOrder: [], viewMode: 'tabs' };
    let confirmed = null;
    let draft = { ...defaults, sectionOrder: [...defaultOrder] };
    let photo = null;
    let removePhoto = false;
    let previewUrl = null;
    let loaded = false;
    let busy = false;
    let conflict = false;
    let legacy = null;
    let recoveringLegacy = false;
    let failedOperation = 'load';
    legacyButton.hidden = true;

    function normalize(value) {
        value = value && typeof value === 'object' ? value : {};
        const themeName = Object.hasOwn(themes, value.themeName) ? value.themeName : 'sena';
        const order = [...new Set(Array.isArray(value.sectionOrder) ? value.sectionOrder : [])].filter(id => Object.hasOwn(labels, id));
        return {
            avatar: avatars.includes(value.avatar) ? value.avatar : defaults.avatar,
            accent: themes[themeName], themeName,
            alias: typeof value.alias === 'string' ? value.alias.trim().slice(0, 30) : '',
            motto: typeof value.motto === 'string' ? value.motto.trim().slice(0, 80) : '',
            background: ['plain', 'dots', 'grid'].includes(value.background) ? value.background : 'plain',
            viewMode: value.viewMode === 'cascade' ? 'cascade' : 'tabs',
            sectionOrder: order.concat(defaultOrder.filter(id => !order.includes(id))),
        };
    }

    function updateControls() {
        saveButton.disabled = !loaded || busy || conflict;
        saveButton.textContent = busy ? 'Espera…' : 'Guardar cambios';
        byId('personalizacion-form-fields').disabled = !loaded || busy;
        byId('btn-reset-personalizacion').disabled = !loaded || busy;
        retryButton.disabled = busy;
        reloadButton.disabled = busy;
        legacyButton.disabled = busy;
        modal.classList.toggle('is-loading', busy);
        modal.setAttribute('aria-busy', String(busy));
    }

    function status(message, kind = 'info') {
        const target = byId('personalizacion-status');
        target.textContent = message;
        target.dataset.kind = kind;
        target.setAttribute('role', kind === 'error' ? 'alert' : 'status');
        byId('personalizacion-global-status').textContent = message;
        byId('personalizacion-global-status').dataset.kind = kind;
        if (kind === 'success' && typeof win.mostrarAviso === 'function') win.mostrarAviso(message, { intent: 'success' });
        retryButton.hidden = true;
        reloadButton.hidden = true;
    }

    function releasePreview() {
        if (previewUrl) win.URL.revokeObjectURL(previewUrl);
        previewUrl = null;
    }

    function syncPhotoPreview() {
        const image = byId('customizer-photo-preview');
        const url = previewUrl || (!removePhoto && confirmed && confirmed.photoUrl);
        image.hidden = !url;
        if (url) image.setAttribute('src', url);
        else image.removeAttribute('src');
        byId('customizer-photo-symbol').hidden = Boolean(url);
        byId('customizer-photo-symbol').textContent = draft.avatar;
        byId('customizer-remove-photo').disabled = !url;
    }

    function moveSection(id, direction) {
        const visibleOrder = draft.sectionOrder.filter(sectionId => sections.has(sectionId));
        const index = visibleOrder.indexOf(id);
        const other = index + direction;
        if (other < 0 || other >= visibleOrder.length) return;
        const actualIndex = draft.sectionOrder.indexOf(id);
        const actualOther = draft.sectionOrder.indexOf(visibleOrder[other]);
        [draft.sectionOrder[actualIndex], draft.sectionOrder[actualOther]] = [draft.sectionOrder[actualOther], draft.sectionOrder[actualIndex]];
        renderOrder();
        status(labels[id] + ' cambió de posición. Guarda para aplicar el orden.');
        const control = byId('customizer-move-' + id + '-' + direction);
        if (control && !control.disabled) control.focus();
        else byId('customizer-move-' + id + '-' + (-direction))?.focus();
    }

    function renderOrder() {
        orderList.replaceChildren();
        const visibleOrder = draft.sectionOrder.filter(id => sections.has(id));
        for (const [index, id] of visibleOrder.entries()) {
            const row = doc.createElement('li');
            const label = doc.createElement('span');
            label.textContent = (index + 1) + '. ' + labels[id];
            row.appendChild(label);
            for (const direction of [-1, 1]) {
                const button = doc.createElement('button');
                button.type = 'button'; button.className = 'btn btn-sm btn-outline';
                button.textContent = direction < 0 ? '↑ Subir' : '↓ Bajar';
                button.setAttribute('aria-label', (direction < 0 ? 'Subir ' : 'Bajar ') + labels[id]);
                button.id = 'customizer-move-' + id + '-' + direction;
                button.disabled = direction < 0 ? index === 0 : index === visibleOrder.length - 1;
                button.addEventListener('click', function () { moveSection(id, direction); });
                row.appendChild(button);
            }
            orderList.appendChild(row);
        }
    }

    function syncDraft() {
        for (const [name, input] of Object.entries(fields)) input.value = draft[name];
        for (const button of doc.querySelectorAll('[data-avatar]')) {
            const selected = button.dataset.avatar === draft.avatar;
            button.classList.toggle('is-selected', selected);
            button.setAttribute('aria-pressed', String(selected));
        }
        for (const button of doc.querySelectorAll('[data-accent]')) {
            const selected = button.dataset.accent === draft.accent;
            button.classList.toggle('is-selected', selected);
            button.setAttribute('aria-pressed', String(selected));
        }
        syncPhotoPreview();
        renderOrder();
    }

    function readDraftFields() {
        for (const [name, input] of Object.entries(fields)) draft[name] = input.value;
    }

    function discardDraft() {
        releasePreview();
        photo = null; removePhoto = false; recoveringLegacy = false;
        photoInput.value = '';
        draft = normalize(confirmed && confirmed.preferences);
        syncDraft();
    }

    function applyConfirmed(result) {
        confirmed = { ...result, preferences: normalize(result.preferences) };
        const preferences = confirmed.preferences;
        const color = preferences.accent;
        const rgb = [1, 3, 5].map(index => parseInt(color.slice(index, index + 2), 16) / 255);
        const linear = rgb.map(value => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4);
        const luminance = linear[0] * 0.2126 + linear[1] * 0.7152 + linear[2] * 0.0722;
        page.style.setProperty('--learner-custom-accent', color);
        page.style.setProperty('--learner-custom-accent-soft', color + '26');
        page.style.setProperty('--learner-accent-foreground', luminance > 0.179 ? '#111827' : '#ffffff');
        page.dataset.learnerBackground = preferences.background;
        byId('learner-display-name').textContent = preferences.alias || config.displayName;
        byId('learner-motto-text').textContent = preferences.motto || '¡Constancia y enfoque para alcanzar tus metas de formación!';
        byId('learner-avatar-display').textContent = preferences.avatar;
        byId('learner-avatar-display').hidden = Boolean(result.photoUrl);
        const image = byId('learner-photo-display');
        image.hidden = !result.photoUrl;
        if (result.photoUrl) image.setAttribute('src', result.photoUrl);
        else image.removeAttribute('src');
        const visibleOrder = preferences.sectionOrder.filter(id => sections.has(id));
        for (const [index, id] of visibleOrder.entries()) page.insertBefore(sections.get(id), slots[index].nextSibling);
        win.dispatchEvent(new win.CustomEvent('learner:preferences-applied', { detail: { preferences } }));
        discardDraft();
    }

    async function request(options) {
        const controller = new win.AbortController();
        const timer = win.setTimeout(function () { controller.abort(); }, 15000);
        try {
            let response;
            try {
                response = await win.fetch(config.endpoint, { credentials: 'same-origin', signal: controller.signal, headers: { Accept: 'application/json', 'X-Requested-With': 'XMLHttpRequest', 'X-Learner-Id': String(config.learnerId) }, ...options });
            } catch (_) {
                throw new Error(controller.signal.aborted ? 'Se agotó el tiempo de espera. Vuelve a intentar. Tus cambios siguen en el formulario.' : 'No se pudo conectar. Revisa tu conexión y vuelve a intentar. Tus cambios siguen en el formulario.');
            }
            let result;
            try { result = await response.json(); }
            catch (_) { throw new Error(controller.signal.aborted ? 'Se agotó el tiempo de espera. Vuelve a intentar.' : 'La sesión o la respuesta del servidor no es válida. Recarga la página e inicia sesión para continuar.'); }
            if (!response.ok || !result || !result.ok || !result.preferences || typeof result.preferences !== 'object' || !Number.isInteger(result.revision) || result.revision < 0 || typeof result.configured !== 'boolean' || (result.photoUrl !== null && typeof result.photoUrl !== 'string')) {
                const error = new Error(result?.detail || result?.error || 'No se pudo confirmar la información. Vuelve a intentar.');
                error.status = response.status;
                throw error;
            }
            return result;
        } finally { win.clearTimeout(timer); }
    }

    function handleError(error, operation) {
        failedOperation = operation;
        conflict = error.status === 409;
        if (error.status === 401 || error.status === 403) { loaded = false; failedOperation = 'load'; }
        status(error.message, 'error');
        if (conflict) reloadButton.hidden = false;
        else retryButton.hidden = false;
    }

    async function load() {
        if (busy) return;
        loaded = false; busy = true; updateControls();
        status('Cargando tus preferencias guardadas…');
        try {
            const result = await request({ method: 'GET' });
            applyConfirmed(result);
            loaded = true; conflict = false;
            legacy = null;
            if (!result.configured) {
                try { const raw = JSON.parse(win.localStorage.getItem(legacyKey)); if (raw && typeof raw === 'object' && !Array.isArray(raw)) legacy = normalize(raw); }
                catch (_) { /* La personalización funciona sin almacenamiento del navegador. */ }
            }
            legacyButton.hidden = !legacy;
            status(result.configured ? 'Tus preferencias están cargadas.' : 'Aún no has personalizado tu panel. Elige cómo quieres verlo y guarda los cambios.');
        } catch (error) { handleError(error, 'load'); }
        finally { busy = false; updateControls(); }
    }

    function open(focusView = false) {
        if (busy) return;
        discardDraft();
        win.abrirModal(modal);
        if (focusView) fields.viewMode.focus();
    }

    function close() {
        if (busy) return;
        discardDraft();
        win.cerrarModal(modal);
    }

    async function save() {
        if (!loaded || busy || conflict) return;
        readDraftFields();
        draft = normalize(draft);
        const body = new win.FormData();
        body.append('preferences', JSON.stringify(draft));
        body.append('revision', String(confirmed.revision));
        body.append('csrf_token', doc.querySelector('meta[name="csrf-token"]').getAttribute('content'));
        if (photo) body.append('photo', photo);
        if (removePhoto) body.append('remove_photo', 'true');
        busy = true; updateControls(); status('Guardando tus cambios en la base de datos…');
        try {
            const result = await request({ method: 'POST', body });
            const removeLegacy = recoveringLegacy;
            applyConfirmed(result);
            if (removeLegacy) {
                try { win.localStorage.removeItem(legacyKey); } catch (_) { /* El servidor ya confirmó la recuperación. */ }
            }
            legacy = null; legacyButton.hidden = true;
            status('Tus cambios quedaron guardados. Se conservarán cuando vuelvas a ingresar.', 'success');
            busy = false; updateControls(); win.cerrarModal(modal);
        } catch (error) { handleError(error, 'save'); }
        finally { busy = false; updateControls(); }
    }

    function changePhoto() {
        const file = photoInput.files[0];
        if (!file) return;
        if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type) || file.size > 2 * 1024 * 1024) {
            status('Elige una foto JPEG, PNG o WebP de máximo 2 MiB.', 'error');
            photoInput.value = ''; return;
        }
        releasePreview();
        photo = file; removePhoto = false;
        previewUrl = win.URL.createObjectURL(file);
        syncPhotoPreview();
        status('La foto está lista para guardar.');
    }

    byId('btn-open-customizer').addEventListener('click', function () { open(); });
    for (const id of ['learner-avatar-disc', 'learner-motto-wrapper']) {
        byId(id).addEventListener('click', function () { open(); });
        byId(id).addEventListener('keydown', function (event) {
            if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); open(); }
        });
    }
    byId('btn-toggle-view-mode').addEventListener('click', function () { open(true); });
    saveButton.addEventListener('click', save);
    retryButton.addEventListener('click', function () { return failedOperation === 'load' ? load() : save(); });
    reloadButton.addEventListener('click', load);
    for (const button of doc.querySelectorAll('[data-close-personalizacion-modal]')) button.addEventListener('click', close);
    modal.addEventListener('cancel', function (event) { event.preventDefault(); close(); });
    modal.addEventListener('close', function () { if (!busy) discardDraft(); });
    modal.addEventListener('click', function (event) { if (event.target === modal) close(); });
    photoInput.addEventListener('change', changePhoto);
    byId('customizer-remove-photo').addEventListener('click', function () {
        releasePreview(); photo = null; photoInput.value = ''; removePhoto = true; syncPhotoPreview();
        status('Se quitará tu foto cuando guardes los cambios.');
    });
    byId('btn-reset-personalizacion').addEventListener('click', function () {
        releasePreview(); photo = null; photoInput.value = ''; removePhoto = true; recoveringLegacy = false; draft = normalize(defaults);
        syncDraft(); status('Los valores iniciales están preparados. Guarda para restablecer tu panel.');
    });
    legacyButton.addEventListener('click', function () {
        if (!legacy || busy || !loaded) return;
        draft = normalize(legacy); recoveringLegacy = true;
        syncDraft(); status('Revisa las preferencias recuperadas de este navegador y guarda para conservarlas en tu cuenta.');
    });
    for (const button of doc.querySelectorAll('[data-avatar]')) button.addEventListener('click', function () { readDraftFields(); draft.avatar = button.dataset.avatar; syncDraft(); });
    for (const button of doc.querySelectorAll('[data-accent]')) button.addEventListener('click', function () { readDraftFields(); draft.accent = button.dataset.accent; draft.themeName = button.dataset.themeName; syncDraft(); });
    for (const button of doc.querySelectorAll('[data-motto]')) button.addEventListener('click', function () { draft.motto = button.dataset.motto; fields.motto.value = draft.motto; });
    const api = { load, open, save, ready: load() };
    return api;
}

if (typeof module !== 'undefined' && module.exports) module.exports = { initLearnerPersonalization };
if (typeof window !== 'undefined' && typeof document !== 'undefined') window.learnerPersonalization = initLearnerPersonalization(document, window);
