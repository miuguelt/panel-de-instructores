function debounce(fn, ms) {
    let timer;
    return function(...args) {
        clearTimeout(timer);
        timer = setTimeout(() => fn.apply(this, args), ms);
    };
}

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
        if (el.dataset.clickableReady === 'true') return;
        el.dataset.clickableReady = 'true';
        el.addEventListener('click', function(e) {
            if (e.target.closest('a, button, input, select, textarea, details, summary, .badge-icon')) return;
            const url = this.getAttribute('data-url');
            if (url) window.location.href = url;
        });
    });
}

// Los iconos del botón se regeneran cuando cambia su contenido. Si Lucide no
// está disponible, el botón conserva su texto y sigue siendo accesible.
function _refrescarIconos() {
    if (window.lucide && typeof window.lucide.createIcons === 'function') {
        try { window.lucide.createIcons(); } catch (_error) { /* sin iconos, sin ruido */ }
    }
}

// Contenido canónico del botón de filtros: icono Lucide + etiqueta y, cuando
// hay filtros activos, el contador en un badge del sistema.
function _etiquetaFiltrar(visibleCount) {
    const icono = '<i data-lucide="search" class="icon-sm" aria-hidden="true"></i>';
    const label = '<span>Filtrar lista</span>';
    if (visibleCount === undefined) return icono + label;
    return icono + label + '<span class="badge badge-success">' + visibleCount + '</span>';
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

        // Toggle button: mantiene 42 px de alto y ancho mínimo desde .btn-sm
        const toggleBtn = document.createElement('button');
        toggleBtn.type = 'button';
        toggleBtn.className = 'btn btn-sm btn-outline table-filter-toggle';
        toggleBtn.innerHTML = _etiquetaFiltrar();
        toggleBtn.setAttribute('aria-expanded', 'false');

        // Create filter UI (hidden by default; .table-filters-container controla la visibilidad)
        const filterContainer = document.createElement('div');
        filterContainer.className = 'table-filters-container';

        const searchInput = document.createElement('input');
        searchInput.type = 'search';
        searchInput.className = 'form-control table-filter-search';
        searchInput.placeholder = 'Escribe para buscar...';
        searchInput.setAttribute('aria-label', 'Buscar en la lista');

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
            stateSelect.className = 'form-control table-filter-select';
            stateSelect.setAttribute('aria-label', 'Filtrar por estado');

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
        clearBtn.hidden = true;
        filterContainer.appendChild(clearBtn);

        // Resumen accesible del resultado
        const resultLabel = document.createElement('span');
        resultLabel.className = 'table-filter-result';
        resultLabel.setAttribute('role', 'status');
        resultLabel.setAttribute('aria-live', 'polite');
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
                celda.className = 'table-filter-empty';
                celda.textContent = 'Ningún registro coincide con el filtro.';
                emptyNotice.appendChild(celda);
                tbody.appendChild(emptyNotice);
            } else {
                emptyNotice = document.createElement('p');
                emptyNotice.className = 'filter-empty-row table-filter-empty';
                emptyNotice.textContent = 'Ningún registro coincide con el filtro.';
                container.appendChild(emptyNotice);
            }
            emptyNotice.hidden = true;
            return emptyNotice;
        };

        // Toggle logic
        let filtersVisible = false;
        const setFiltersVisible = (visible) => {
            filtersVisible = visible;
            toggleBtn.setAttribute('aria-expanded', visible ? 'true' : 'false');
            filterContainer.classList.toggle('is-open', visible);
            toggleBtn.classList.toggle('is-active', visible);
        };

        toggleBtn.addEventListener('click', () => {
            setFiltersVisible(!filtersVisible);
            if (filtersVisible) searchInput.focus();
        });

        // Filter function
        const runFilters = () => {
            requestAnimationFrame(() => {
                const terminos = _filtroTerminos(searchInput.value);
                const stateTerm = stateSelect ? stateSelect.value : '';
                const activo = terminos.length > 0 || stateTerm !== '';
                let visibleCount = 0;

                items.forEach(item => {
                    const itemState = item.getAttribute('data-estado') || '';

                    const matchesSearch = _filtroCoincide(item.textContent, terminos);
                    const matchesState = stateTerm === '' || itemState === stateTerm;

                    if (matchesSearch && matchesState) {
                        item.hidden = false;
                        visibleCount++;
                    } else {
                        item.hidden = true;
                    }
                });

                // Highlight button if filters are active
                if (activo) {
                    toggleBtn.innerHTML = _etiquetaFiltrar(visibleCount);
                    _refrescarIconos();
                    resultLabel.textContent = visibleCount === 1
                        ? '1 registro visible de ' + items.length
                        : visibleCount + ' registros visibles de ' + items.length;
                } else {
                    toggleBtn.innerHTML = _etiquetaFiltrar();
                    _refrescarIconos();
                    resultLabel.textContent = '';
                }
                clearBtn.hidden = !activo;

                if (activo && visibleCount === 0) {
                    buildEmptyNotice().hidden = false;
                } else if (emptyNotice) {
                    emptyNotice.hidden = true;
                }
            });
        };

        // Al filtrar se conserva el punto de lectura: el bloque de filtros no se
        // mueve de la pantalla y, si había quedado arriba, la vista vuelve a él.
        const applyFilters = () => {
            if (window.FiltroVista) window.FiltroVista.aplicar(toolbar, runFilters);
            else runFilters();
        };

        searchInput.addEventListener('input', debounce(applyFilters, 200));
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

        // Insert before the container
        container.parentNode.insertBefore(toolbar, container);

        // Los iconos del botón se crean después de insertarlo en el documento.
        _refrescarIconos();

        // Initial apply if default is set (sin mover la vista en la carga inicial)
        runFilters();
    });
}
