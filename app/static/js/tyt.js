(() => {
    const search = document.getElementById('tyt-search');
    const filter = document.getElementById('tyt-filter');
    if (!search || !filter) return;
    const rows = [...document.querySelectorAll('[data-tyt-row]')];
    const normalize = text => text.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('es-CO');
    function update() {
        const query = normalize(search.value.trim());
        let visible = 0;
        rows.forEach(row => {
            const matches = normalize(row.dataset.name).includes(query)
                && (filter.value === 'todos' || row.dataset.status === filter.value);
            row.hidden = !matches;
            if (matches) visible++;
        });
        document.getElementById('tyt-results-count').textContent = `${visible} de ${rows.length} aprendices`;
        document.getElementById('tyt-no-results').hidden = visible > 0;
    }
    search.addEventListener('input', update);
    filter.addEventListener('change', update);
})();
