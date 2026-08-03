(function () {
    function normalize(value) {
        if (window.FiltroVista) return window.FiltroVista.normalizar(value);
        return (value || '')
            .toLocaleLowerCase('es')
            .normalize('NFD')
            .replace(/[\u0300-\u036f]/g, '');
    }

    function initFollowupFilters() {
        const list = document.querySelector('[data-followup-list]');
        if (!list || list.dataset.followupReady === 'true') return;

        const cards = Array.from(list.querySelectorAll('[data-followup-case]'));
        const searchInput = document.querySelector('[data-followup-search]');
        const prioritySelect = document.querySelector('[data-followup-priority]');
        const statusSelect = document.querySelector('[data-followup-status]');
        const count = document.querySelector('[data-followup-count]');
        const emptyState = document.querySelector('[data-followup-empty]');
        const toolbar = document.querySelector('.followup-toolbar') || document.querySelector('.followup-filters');
        if (!searchInput || !prioritySelect || !statusSelect || !count) return;

        const filterAction = function () {
            const searchTerm = normalize(searchInput.value);
            const priority = prioritySelect.value;
            const status = statusSelect.value;
            let visible = 0;

            cards.forEach(function (card) {
                const matchesSearch = normalize(card.dataset.caseSearch).includes(searchTerm);
                const matchesPriority = !priority || card.dataset.casePriority === priority;
                const matchesStatus = !status || card.dataset.caseStatus === status;
                const shouldShow = matchesSearch && matchesPriority && matchesStatus;
                card.hidden = !shouldShow;
                if (shouldShow) visible += 1;
            });

            count.textContent = `${visible} caso${visible === 1 ? '' : 's'}`;
            if (emptyState) emptyState.hidden = visible !== 0;
        };

        const applyFilters = function () {
            if (window.FiltroVista && toolbar) {
                window.FiltroVista.aplicar(toolbar, filterAction);
            } else {
                filterAction();
            }
        };

        [searchInput, prioritySelect, statusSelect].forEach(function (control) {
            control.addEventListener('input', applyFilters);
            control.addEventListener('change', applyFilters);
        });
        list.dataset.followupReady = 'true';
        applyFilters();
    }

    document.addEventListener('DOMContentLoaded', initFollowupFilters);
    document.body.addEventListener('htmx:afterSwap', initFollowupFilters);
})();
