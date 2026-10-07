/* Metas y preferencias de lectura del aprendiz, confirmadas por el servidor. */
'use strict';

function initLearnerExperience(doc = document, win = window) {
    const root = doc.getElementById('panel-aprendiz-root');
    const section = doc.getElementById('aprendiz-experiencia');
    const seedElement = doc.getElementById('aprendiz-experiencia-data');
    if (!root || !section || !seedElement || !root.dataset.experienciaUrl) return null;
    const byId = id => doc.getElementById(id);
    const fields = {
        weeklyGoal: byId('experience-weekly-goal'), notificationMode: byId('experience-notification-mode'),
        rankingVisible: byId('experience-ranking-visible'), reducedMotion: byId('experience-reduced-motion'), density: byId('experience-density'),
    };
    const tabs = { resumen: 'Resumen', evidencias: 'Mis evidencias', grupo: 'Mi grupo', juicios: 'Juicios de evaluación', rendimiento: 'Rendimiento', convivencia: 'Aseo y convivencia' };
    const saveButton = byId('experience-save');
    const retryButton = byId('experience-retry');
    const reloadButton = byId('experience-reload');
    const resumeButton = byId('experience-resume');
    let seed = {};
    try { seed = JSON.parse(seedElement.textContent) || {}; } catch (_) { /* La lectura de la API permite recuperar una vista incompleta. */ }
    const weeklyCount = Number.isInteger(seed.weekly?.count) && seed.weekly.count >= 0 ? seed.weekly.count : 0;
    let confirmed = null;
    let draft = null;
    let loaded = false;
    let busy = false;
    let conflict = false;
    let generation = 0;
    let debounceTimer = null;
    let failedOperation = 'save';

    function normalize(preferences) {
        const resume = preferences.resume;
        return {
            weeklyGoal: preferences.weeklyGoal,
            notificationMode: preferences.notificationMode,
            rankingVisible: preferences.rankingVisible,
            reducedMotion: preferences.reducedMotion,
            density: preferences.density,
            resume: resume && Object.hasOwn(tabs, resume.tab) && (resume.taskId === null || (Number.isInteger(resume.taskId) && resume.taskId > 0)) ? { tab: resume.tab, taskId: resume.taskId } : null,
        };
    }

    function validResult(result) {
        const preferences = result?.preferences;
        return Boolean(result?.ok && Number.isInteger(result.revision) && result.revision >= 0 && preferences &&
            Number.isInteger(preferences.weeklyGoal) && preferences.weeklyGoal >= 0 && preferences.weeklyGoal <= 20 &&
            ['all', 'important', 'quiet'].includes(preferences.notificationMode) &&
            typeof preferences.rankingVisible === 'boolean' && typeof preferences.reducedMotion === 'boolean' &&
            ['comfortable', 'compact'].includes(preferences.density));
    }

    function controls() {
        saveButton.disabled = !loaded || busy || conflict;
        saveButton.textContent = busy ? 'Guardando…' : 'Guardar ajustes';
        for (const field of Object.values(fields)) field.disabled = !loaded;
        retryButton.disabled = busy;
        reloadButton.disabled = busy;
        section.setAttribute('aria-busy', String(busy));
    }

    function status(message, kind = 'info') {
        const target = byId('experience-status');
        target.textContent = message; target.dataset.kind = kind;
        target.setAttribute('role', kind === 'error' ? 'alert' : 'status');
        retryButton.hidden = true; reloadButton.hidden = true;
    }

    function clearDebounce() {
        if (debounceTimer !== null) win.clearTimeout(debounceTimer);
        debounceTimer = null;
    }

    function syncFields() {
        for (const [name, field] of Object.entries(fields)) {
            if (typeof draft[name] === 'boolean') field.checked = draft[name];
            else field.value = String(draft[name]);
        }
    }

    function destination(value) {
        if (!value || !Object.hasOwn(tabs, value.tab)) return null;
        const id = Number(value.taskId);
        const found = Number.isInteger(id) && id > 0 && Array.from(root.querySelectorAll('[data-experience-task-id]')).some(task => Number(task.dataset.experienceTaskId) === id);
        return { tab: value.tab, taskId: found ? id : null };
    }

    function applyConfirmed(result) {
        confirmed = { preferences: normalize(result.preferences), revision: result.revision };
        const preferences = confirmed.preferences;
        root.classList.toggle('experience-reduced-motion', preferences.reducedMotion);
        root.dataset.experienceDensity = preferences.density;
        root.dataset.experienceNotificationMode = preferences.notificationMode;
        for (const notice of root.querySelectorAll('[data-experience-notice]')) {
            if (notice.dataset.experienceNotice === 'optional' && notice.getAttribute('role') !== 'alert') notice.hidden = preferences.notificationMode !== 'all';
        }
        for (const ranking of root.querySelectorAll('[data-experience-ranking]')) ranking.hidden = !preferences.rankingVisible;
        const target = preferences.weeklyGoal;
        const percent = target > 0 ? Math.min(100, Math.round(100 * weeklyCount / target)) : 0;
        byId('experience-weekly-count').textContent = String(weeklyCount);
        byId('experience-weekly-target').textContent = String(target);
        const progress = byId('experience-weekly-progress');
        progress.style.setProperty('--experience-percent', percent + '%');
        progress.setAttribute('aria-valuenow', String(percent));
        progress.setAttribute('aria-valuetext', target > 0 ? weeklyCount + ' de ' + target + ' evidencias entregadas esta semana' : 'Meta semanal en pausa');
        byId('experience-weekly-summary').textContent = target === 0 ? 'Tu meta semanal está en pausa.' : weeklyCount >= target ? 'Alcanzaste tu meta de esta semana.' : 'Te faltan ' + (target - weeklyCount) + ' evidencias para alcanzar tu meta.';
        const resume = destination(preferences.resume);
        resumeButton.hidden = !resume;
        if (resume) resumeButton.textContent = 'Continuar en ' + tabs[resume.tab];
    }

    function readFields() {
        const value = fields.weeklyGoal.value.trim();
        const goal = Number(value);
        if (!value || !Number.isInteger(goal) || goal < 0 || goal > 20) { status('Elige una meta semanal con un número entero entre 0 y 20.', 'error'); return false; }
        if (!['all', 'important', 'quiet'].includes(fields.notificationMode.value) || !['comfortable', 'compact'].includes(fields.density.value)) {
            status('Revisa el modo de avisos y la densidad antes de guardar.', 'error'); return false;
        }
        draft.weeklyGoal = goal;
        draft.notificationMode = fields.notificationMode.value;
        draft.density = fields.density.value;
        draft.rankingVisible = fields.rankingVisible.checked;
        draft.reducedMotion = fields.reducedMotion.checked;
        return true;
    }

    function scheduleSave() {
        clearDebounce();
        if (!loaded || conflict) return;
        debounceTimer = win.setTimeout(function () { debounceTimer = null; return save(); }, 600);
    }

    function changed() {
        clearDebounce();
        if (!loaded) return;
        generation++;
        if (conflict || !readFields()) return;
        status('Tienes ajustes pendientes. Se guardarán en un momento.');
        scheduleSave();
    }

    function captureResume(value) {
        const next = destination(value);
        if (!loaded || !next) return;
        draft.resume = next; generation++;
        scheduleSave();
    }

    function navigate(value) {
        const next = destination(value);
        if (!next) return;
        win.dispatchEvent(new win.CustomEvent('learner:navigate', { detail: { ...next, clearTaskFilters: next.taskId !== null } }));
        captureResume(next);
    }

    async function request(options) {
        const controller = new win.AbortController();
        const timer = win.setTimeout(function () { controller.abort(); }, 15000);
        try {
            let response;
            try {
                response = await win.fetch(root.dataset.experienciaUrl, { credentials: 'same-origin', signal: controller.signal,
                    headers: { Accept: 'application/json', 'Content-Type': 'application/json', 'X-CSRFToken': doc.querySelector('meta[name="csrf-token"]').getAttribute('content'), 'X-Learner-Id': root.dataset.learnerId }, ...options });
            } catch (_) { throw new Error(controller.signal.aborted ? 'Se agotó el tiempo de espera. Tus ajustes siguen pendientes; vuelve a intentar.' : 'No se pudo conectar. Revisa tu conexión y vuelve a intentar.'); }
            let result;
            try { result = await response.json(); }
            catch (_) { throw new Error(controller.signal.aborted ? 'Se agotó el tiempo de espera. Vuelve a intentar.' : 'La sesión o la respuesta no es válida. Recarga la página para continuar.'); }
            if (!response.ok || !validResult(result)) {
                const error = new Error(result?.detail || result?.error || 'No se pudieron confirmar los ajustes. Vuelve a intentar.'); error.status = response.status; throw error;
            }
            return result;
        } finally { win.clearTimeout(timer); }
    }

    function failure(error, operation) {
        clearDebounce(); failedOperation = operation; conflict = error.status === 409;
        if (error.status === 401 || error.status === 403) { loaded = false; failedOperation = 'load'; }
        status(error.message, 'error');
        retryButton.textContent = failedOperation === 'load' ? 'Volver a cargar ajustes' : 'Reintentar guardado';
        if (conflict) reloadButton.hidden = false;
        else retryButton.hidden = false;
    }

    async function load() {
        if (busy) return;
        clearDebounce(); busy = true; loaded = false; controls(); status('Cargando tus ajustes guardados…');
        try {
            applyConfirmed(await request({ method: 'GET' }));
            draft = normalize(confirmed.preferences); syncFields(); loaded = true; conflict = false;
            status(confirmed.revision === 0 ? 'Tus ajustes iniciales están cargados. Los cambios se guardan automáticamente.' : 'Tus ajustes guardados están cargados.');
        } catch (error) { failure(error, 'load'); }
        finally { busy = false; controls(); }
    }

    async function save() {
        clearDebounce();
        if (!loaded || busy || conflict || !readFields()) return;
        const sentGeneration = generation;
        const preferences = normalize(draft);
        busy = true; controls(); status('Guardando tus ajustes en tu cuenta…');
        let followup = false;
        try {
            const result = await request({ method: 'POST', body: JSON.stringify({ preferences, revision: confirmed.revision }) });
            applyConfirmed(result);
            if (generation === sentGeneration) {
                draft = normalize(confirmed.preferences); syncFields();
                status('Tus ajustes quedaron guardados.', 'success');
                if (confirmed.preferences.notificationMode !== 'quiet' && typeof win.mostrarAviso === 'function') win.mostrarAviso('Tus ajustes quedaron guardados.', { intent: 'success' });
            } else { followup = true; status('Se guardó el primer cambio. Tus últimos ajustes siguen pendientes.'); }
        } catch (error) { failure(error, 'save'); }
        finally { busy = false; controls(); if (followup) scheduleSave(); }
    }

    for (const field of Object.values(fields)) { field.addEventListener('change', changed); field.addEventListener('input', changed); }
    saveButton.addEventListener('click', save);
    retryButton.addEventListener('click', function () { return failedOperation === 'load' ? load() : save(); });
    reloadButton.addEventListener('click', load);
    byId('experience-next-action').addEventListener('click', function () { navigate(seed.next_action || { tab: 'resumen', taskId: null }); });
    resumeButton.addEventListener('click', function () { navigate(confirmed?.preferences.resume); });
    for (const button of root.querySelectorAll('.learner-tab-btn')) button.addEventListener('click', function () { captureResume({ tab: button.dataset.tabTarget, taskId: null }); });
    function taskInteraction(event) {
        const task = event.target.closest?.('[data-experience-task-id]');
        if (task) captureResume({ tab: task.dataset.experienceTaskTab || 'evidencias', taskId: Number(task.dataset.experienceTaskId) });
    }
    root.addEventListener('click', taskInteraction);
    root.addEventListener('toggle', taskInteraction, true);
    win.addEventListener('learner:location', function (event) { captureResume(event.detail); });
    let ready;
    const initialResult = { ...seed, ok: true };
    if (validResult(initialResult)) { applyConfirmed(initialResult); draft = normalize(confirmed.preferences); syncFields(); loaded = true; controls(); status(confirmed.revision === 0 ? 'Tus ajustes iniciales están cargados. Los cambios se guardan automáticamente.' : 'Tus ajustes están guardados en tu cuenta.'); ready = Promise.resolve(); }
    else ready = load();
    return { save, load, navigate, ready };
}

if (typeof module !== 'undefined' && module.exports) module.exports = { initLearnerExperience };
if (typeof window !== 'undefined' && typeof document !== 'undefined') window.learnerExperience = initLearnerExperience(document, window);
