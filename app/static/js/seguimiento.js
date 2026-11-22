/* Filtros de la bandeja de casos de seguimiento (búsqueda, prioridad y estado). */
'use strict';

function initFollowupFilters(doc = document, win = window) {
    const list = doc.querySelector('[data-followup-list]');
    if (!list || list.dataset.followupReady === 'true') return;

    const cards = Array.from(list.querySelectorAll('[data-followup-case]'));
    const searchInput = doc.querySelector('[data-followup-search]');
    const prioritySelect = doc.querySelector('[data-followup-priority]');
    const statusSelect = doc.querySelector('[data-followup-status]');
    const count = doc.querySelector('[data-followup-count]');
    const emptyState = doc.querySelector('[data-followup-empty]');
    const toolbar = doc.querySelector('.followup-toolbar') || doc.querySelector('.followup-filters');
    if (!searchInput || !prioritySelect || !statusSelect || !count) return;

    const normalize = value => (win.FiltroVista
        ? win.FiltroVista.normalizar(value)
        : String(value || '').toLocaleLowerCase('es').normalize('NFD').replace(/[̀-ͯ]/g, ''));

    const filterAction = function () {
        const searchTerm = normalize(searchInput.value);
        const priority = prioritySelect.value;
        const status = statusSelect.value;
        let visible = 0;
        cards.forEach(function (card) {
            const shouldShow = normalize(card.dataset.caseSearch).includes(searchTerm)
                && (!priority || card.dataset.casePriority === priority)
                && (!status || card.dataset.caseStatus === status);
            card.hidden = !shouldShow;
            if (shouldShow) visible += 1;
        });
        count.textContent = `${visible} caso${visible === 1 ? '' : 's'}`;
        if (emptyState) emptyState.hidden = visible !== 0;
    };

    // Solo los cambios del usuario conservan la posición de lectura alrededor de
    // los filtros; al abrir la página la vista debe quedarse arriba, en el título.
    const applyFilters = function () {
        if (win.FiltroVista && toolbar) win.FiltroVista.aplicar(toolbar, filterAction);
        else filterAction();
    };
    const debouncedApply = (win.FiltroVista && win.FiltroVista.debounce)
        ? win.FiltroVista.debounce(applyFilters, 180)
        : applyFilters;

    searchInput.addEventListener('input', debouncedApply);
    [prioritySelect, statusSelect].forEach(control => control.addEventListener('change', applyFilters));
    list.dataset.followupReady = 'true';
    filterAction();
}

/** Inicializa al cargar y tras cada intercambio de htmx. */
function registrar(doc, win) {
    const iniciar = () => initFollowupFilters(doc, win);
    doc.addEventListener('DOMContentLoaded', iniciar);
    doc.body.addEventListener('htmx:afterSwap', iniciar);
    return iniciar;
}

if (typeof module !== 'undefined' && module.exports) module.exports = { initFollowupFilters, registrar };
if (typeof window !== 'undefined' && typeof document !== 'undefined') registrar(document, window);
