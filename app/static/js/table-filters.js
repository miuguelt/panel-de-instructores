document.addEventListener('DOMContentLoaded', function() {
    initTableFilters();
    initClickableRows();
});

// For HTMX navigation if needed
document.body.addEventListener('htmx:afterSwap', function() {
    initTableFilters();
    initClickableRows();
});

function initClickableRows() {
    document.querySelectorAll('.table-clickable, .ranking-card').forEach(el => {
        el.addEventListener('click', function(e) {
            if (e.target.closest('a, button, input, select, textarea, details, summary, .badge-icon')) return;
            const url = this.getAttribute('data-url');
            if (url) window.location.href = url;
        });
    });
}

// Búsqueda sin distinguir tildes ni mayúsculas; se exige que estén todos los términos.
function _filtroTerminos(consulta) {
    if (window.FiltroVista) return window.FiltroVista.terminos(consulta);
    return (consulta || '').toLowerCase().split(/\s+/).filter(Boolean);
}

function _filtroCoincide(texto, terminos) {
    if (window.FiltroVista) return window.FiltroVista.coincide(texto, terminos);
    const base = (texto || '').toLowerCase();
    return terminos.every(t => base.indexOf(t) !== -1);
}

function initTableFilters() {
    const tableContainers = document.querySelectorAll('.table-responsive, .ranking-mobile');

    tableContainers.forEach((container, idx) => {
        // Las vistas con filtros propios (p. ej. aprendices por estado) se
        // marcan con data-manual-filters para evitar toolbars duplicados.
        if (container.hasAttribute('data-manual-filters')) {
            return;
        }

        // Prevent duplicate filters if already added
        if (container.previousElementSibling && container.previousElementSibling.classList.contains('table-toolbar')) {
            return;
        }

        // Only add filters if the container has elements to filter (table rows or articles)
        const hasRows = container.querySelector('tbody tr');
        const hasArticles = container.querySelectorAll('article.ranking-card').length > 0;

        if (!hasRows && !hasArticles) return;

        // Toolbar wrapper (contains the toggle button and the filter container)
        const toolbar = document.createElement('div');
        toolbar.className = 'table-toolbar';
        toolbar.setAttribute('data-filter-region', 'table-filter-toolbar-' + idx);
        if (container.closest('.ranking-card-container')) {
            toolbar.classList.add(container.classList.contains('ranking-mobile') ? 'table-toolbar-mobile' : 'table-toolbar-desktop');
        }
        toolbar.style.cssText = 'display: flex; flex-direction: column; align-items: flex-end; margin-bottom: 12px;';

        // Toggle button
        const toggleBtn = document.createElement('button');
        toggleBtn.type = 'button';
        toggleBtn.className = 'btn btn-sm btn-outline';
        toggleBtn.innerHTML = '🔍 Filtrar lista';
        toggleBtn.setAttribute('aria-expanded', 'false');
        toggleBtn.style.cssText = 'border-radius: 20px; font-size: 12px; padding: 4px 12px; background: var(--bg-glass); color: var(--text-main); border: 1px solid var(--border-glass); transition: all 0.2s;';

        // Create filter UI (hidden by default)
        const filterContainer = document.createElement('div');
        filterContainer.className = 'table-filters-container';
        filterContainer.style.cssText = 'display: none; gap: 12px; flex-wrap: wrap; align-items: center; background: var(--bg-glass); backdrop-filter: var(--blur-glass); padding: 12px 16px; border-radius: var(--radius-sm); border: 1px solid var(--border-glass); box-shadow: var(--shadow); margin-top: 8px; width: 100%; animation: slideDown 0.2s ease-out;';

        const searchInput = document.createElement('input');
        searchInput.type = 'search';
        searchInput.className = 'form-control';
        searchInput.placeholder = 'Escribe para buscar...';
        searchInput.setAttribute('aria-label', 'Buscar en la lista');
        searchInput.style.cssText = 'flex: 1; min-width: 200px; padding: 8px 12px; border-radius: 6px; border: 1px solid var(--border-divider); background: var(--input-bg); color: var(--text-strong);';

        filterContainer.appendChild(searchInput);

        // Check if there are states in the data
        const items = hasRows ? container.querySelectorAll('tbody tr') : container.querySelectorAll('article.ranking-card');
        const states = new Set();
        let hasDataEstado = false;

        items.forEach(item => {
            if (item.hasAttribute('data-estado')) {
                hasDataEstado = true;
                states.add(item.getAttribute('data-estado'));
            }
        });

        let stateSelect = null;
        if (hasDataEstado) {
            stateSelect = document.createElement('select');
            stateSelect.className = 'form-control';
            stateSelect.setAttribute('aria-label', 'Filtrar por estado');
            stateSelect.style.cssText = 'width: auto; min-width: 150px; padding: 8px 12px; border-radius: 6px; border: 1px solid var(--border-divider); background: var(--input-bg); color: var(--text-strong);';

            const allOption = document.createElement('option');
            allOption.value = '';
            allOption.textContent = 'Todos los estados';
            stateSelect.appendChild(allOption);

            // Add options based on available states
            Array.from(states).sort().forEach(state => {
                if(state) {
                    const option = document.createElement('option');
                    option.value = state;
                    option.textContent = state.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
                    stateSelect.appendChild(option);
                }
            });

            // Por defecto se muestran todos los estados: preseleccionar
            // EN_FORMACION ocultaba aprendices condicionados, retirados, etc.
            filterContainer.appendChild(stateSelect);
        }

        // Botón para limpiar los filtros sin borrar a mano
        const clearBtn = document.createElement('button');
        clearBtn.type = 'button';
        clearBtn.className = 'btn btn-sm btn-outline';
        clearBtn.textContent = 'Limpiar';
        clearBtn.style.cssText = 'padding: 6px 12px; border-radius: 6px; font-size: 12px;';
        clearBtn.hidden = true;
        filterContainer.appendChild(clearBtn);

        // Resumen accesible del resultado
        const resultLabel = document.createElement('span');
        resultLabel.setAttribute('role', 'status');
        resultLabel.setAttribute('aria-live', 'polite');
        resultLabel.style.cssText = 'font-size: 12px; color: var(--text-muted);';
        filterContainer.appendChild(resultLabel);

        // Aviso cuando ningún elemento coincide
        const tbody = hasRows ? container.querySelector('tbody') : null;
        let emptyNotice = null;
        const buildEmptyNotice = () => {
            if (emptyNotice) return emptyNotice;
            if (tbody) {
                const columnas = container.querySelectorAll('thead th').length || 1;
                emptyNotice = document.createElement('tr');
                emptyNotice.className = 'filter-empty-row';
                const celda = document.createElement('td');
                celda.colSpan = columnas;
                celda.style.cssText = 'text-align: center; padding: 18px; color: var(--text-muted);';
                celda.textContent = 'Ningún registro coincide con el filtro.';
                emptyNotice.appendChild(celda);
                tbody.appendChild(emptyNotice);
            } else {
                emptyNotice = document.createElement('p');
                emptyNotice.className = 'filter-empty-row';
                emptyNotice.style.cssText = 'text-align: center; padding: 18px; color: var(--text-muted);';
                emptyNotice.textContent = 'Ningún registro coincide con el filtro.';
                container.appendChild(emptyNotice);
            }
            return emptyNotice;
        };

        // Toggle logic
        let filtersVisible = false;
        const setFiltersVisible = (visible) => {
            filtersVisible = visible;
            toggleBtn.setAttribute('aria-expanded', visible ? 'true' : 'false');
            if (visible) {
                filterContainer.style.display = 'flex';
                toggleBtn.style.background = 'var(--sena-green-light)';
                toggleBtn.style.borderColor = 'var(--accent-primary)';
                toggleBtn.style.color = 'var(--accent-hover)';
            } else {
                filterContainer.style.display = 'none';
                toggleBtn.style.background = 'var(--bg-glass)';
                toggleBtn.style.borderColor = 'var(--border-glass)';
                toggleBtn.style.color = 'var(--text-main)';
            }
        };

        toggleBtn.addEventListener('click', () => {
            setFiltersVisible(!filtersVisible);
            if (filtersVisible) searchInput.focus();
        });

        // Filter function
        const runFilters = () => {
            const terminos = _filtroTerminos(searchInput.value);
            const stateTerm = stateSelect ? stateSelect.value : '';
            const activo = terminos.length > 0 || stateTerm !== '';
            let visibleCount = 0;

            items.forEach(item => {
                const itemState = item.getAttribute('data-estado') || '';

                const matchesSearch = _filtroCoincide(item.textContent, terminos);
                const matchesState = stateTerm === '' || itemState === stateTerm;

                if (matchesSearch && matchesState) {
                    item.style.display = '';
                    visibleCount++;
                } else {
                    item.style.display = 'none';
                }
            });

            // Highlight button if filters are active
            if (activo) {
                toggleBtn.innerHTML = `🔍 Filtrar lista <span class="badge badge-success" style="margin-left:4px;">${visibleCount}</span>`;
                resultLabel.textContent = visibleCount === 1
                    ? '1 registro visible de ' + items.length
                    : visibleCount + ' registros visibles de ' + items.length;
            } else {
                toggleBtn.innerHTML = '🔍 Filtrar lista';
                resultLabel.textContent = '';
            }
            clearBtn.hidden = !activo;

            if (activo && visibleCount === 0) {
                buildEmptyNotice().style.display = '';
            } else if (emptyNotice) {
                emptyNotice.style.display = 'none';
            }
        };

        // Al filtrar se conserva el punto de lectura: el bloque de filtros no se
        // mueve de la pantalla y, si había quedado arriba, la vista vuelve a él.
        const applyFilters = () => {
            if (window.FiltroVista) window.FiltroVista.aplicar(toolbar, runFilters);
            else runFilters();
        };

        searchInput.addEventListener('input', applyFilters);
        searchInput.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && searchInput.value !== '') {
                e.preventDefault();
                searchInput.value = '';
                applyFilters();
            }
        });
        if (stateSelect) {
            stateSelect.addEventListener('change', applyFilters);
        }
        clearBtn.addEventListener('click', () => {
            searchInput.value = '';
            if (stateSelect) stateSelect.value = '';
            applyFilters();
            searchInput.focus();
        });

        // Assemble toolbar
        toolbar.appendChild(toggleBtn);
        toolbar.appendChild(filterContainer);

        // Add CSS animation if not exists
        if (!document.getElementById('filter-animations')) {
            const style = document.createElement('style');
            style.id = 'filter-animations';
            style.innerHTML = `@keyframes slideDown { from { opacity: 0; transform: translateY(-10px); } to { opacity: 1; transform: translateY(0); } }`;
            document.head.appendChild(style);
        }

        // Insert before the container
        container.parentNode.insertBefore(toolbar, container);

        // Initial apply if default is set (sin mover la vista en la carga inicial)
        runFilters();
    });
}
