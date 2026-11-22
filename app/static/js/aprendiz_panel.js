/* Panel del aprendiz: calendario de asistencia, pestañas, filtros de evidencias,
   portafolio digital e inspector de la curva de rendimiento.

   Los datos llegan del servidor como atributos data-* o JSON en
   <script type="application/json">; este archivo no depende de Jinja. */
'use strict';

const PESTANAS = ['resumen', 'evidencias', 'grupo', 'juicios', 'rendimiento', 'convivencia'];
const PESTANA_POR_ANCLA = {
    '#tab-resumen': 'resumen', '#seccion-progreso': 'resumen',
    '#tab-evidencias': 'evidencias', '#seccion-tareas': 'evidencias',
    '#tab-grupo': 'grupo', '#seccion-grupo-trabajo': 'grupo',
    '#tab-juicios': 'juicios', '#seccion-juicios': 'juicios',
    '#tab-rendimiento': 'rendimiento', '#seccion-ranking': 'rendimiento',
    '#tab-convivencia': 'convivencia', '#seccion-aseo': 'convivencia',
};
const MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'];
const DIAS = ['lu', 'ma', 'mi', 'ju', 'vi', 'sá', 'do'];
const CHIPS = { all: 'chip-count-all', pending: 'chip-count-pending', urgent: 'chip-count-urgent', extemp: 'chip-count-extemp', plan: 'chip-count-plan', delivered: 'chip-count-delivered' };

/** Pestaña inicial: el ancla de la URL manda; si no hay, la última guardada; si no, el resumen. */
function pestanaInicial(ancla, guardada) {
    if (PESTANA_POR_ANCLA[ancla]) return PESTANA_POR_ANCLA[ancla];
    return PESTANAS.includes(guardada) ? guardada : 'resumen';
}

function aIso(anio, mes, dia) {
    return `${anio}-${String(mes + 1).padStart(2, '0')}-${String(dia).padStart(2, '0')}`;
}

function formatoFecha(iso) {
    const [anio, mes, dia] = iso.split('-');
    return `${dia}/${mes}/${anio}`;
}

/** Datos de filtrado de una evidencia leídos de sus atributos data-task-*. */
function datosEvidencia(item) {
    return {
        titulo: item.getAttribute('data-task-title') || '',
        descripcion: item.getAttribute('data-task-desc') || '',
        estado: item.getAttribute('data-task-status') || '',
        urgente: item.getAttribute('data-task-urgent') === 'true',
        extemporanea: item.getAttribute('data-task-extemp') === 'true',
        plan: item.getAttribute('data-task-plan') === 'true',
    };
}

/** ¿La evidencia cumple el filtro activo y la búsqueda? */
function coincideEvidencia(datos, filtro, busqueda) {
    if (busqueda && !datos.titulo.includes(busqueda) && !datos.descripcion.includes(busqueda)) return false;
    const pendiente = datos.estado === 'pending';
    switch (filtro) {
        case 'pending': return pendiente;
        case 'urgent': return datos.urgente && pendiente;
        case 'extemporaneous': return datos.extemporanea && pendiente;
        case 'plan': return datos.plan;
        case 'delivered': return datos.estado === 'delivered';
        default: return true;
    }
}

/** Conteos de los chips de filtro. */
function contarChips(lista) {
    const conteo = { all: 0, pending: 0, urgent: 0, extemp: 0, plan: 0, delivered: 0 };
    for (const datos of lista) {
        conteo.all += 1;
        if (datos.estado === 'delivered') conteo.delivered += 1;
        else {
            conteo.pending += 1;
            if (datos.urgente) conteo.urgent += 1;
            if (datos.extemporanea) conteo.extemp += 1;
        }
        if (datos.plan) conteo.plan += 1;
    }
    return conteo;
}

/** Calendario mensual de asistencia del aprendiz. */
function initCalendarioAsistencia(doc = document, hoy = new Date()) {
    const calendario = doc.querySelector('.learner-attendance-calendar');
    const fuente = doc.getElementById('asistencia-calendario-data');
    if (!calendario || !fuente) return null;
    let registros = {};
    try { registros = JSON.parse(fuente.textContent) || {}; } catch (_) { /* Sin datos legibles el calendario se muestra vacío. */ }
    const grilla = calendario.querySelector('[data-learner-calendar-grid]');
    const titulo = calendario.querySelector('[data-learner-calendar-month]');
    const detalle = calendario.querySelector('[data-learner-calendar-detail]');
    const visible = new Date(hoy.getFullYear(), hoy.getMonth(), 1);

    function mostrarDetalle(iso, registro) {
        if (!registro) {
            detalle.textContent = 'No hay una marcación registrada para este día.';
            return;
        }
        const causal = registro.causal ? ` · ${registro.causal}` : '';
        const fecha = doc.createElement('strong');
        fecha.textContent = formatoFecha(iso);
        detalle.replaceChildren(fecha, doc.createTextNode(` · ${registro.etiqueta || registro.estado}${causal}`));
    }

    function celda(clase, texto) {
        const elemento = doc.createElement('div');
        elemento.className = clase;
        if (texto) {
            elemento.setAttribute('role', 'columnheader');
            elemento.textContent = texto;
        } else elemento.setAttribute('aria-hidden', 'true');
        return elemento;
    }

    function dibujar() {
        const anio = visible.getFullYear();
        const mes = visible.getMonth();
        titulo.textContent = `${MESES[mes]} ${anio}`;
        grilla.replaceChildren();
        DIAS.forEach(nombre => grilla.appendChild(celda('learner-calendar-weekday', nombre)));
        const desplazamiento = (new Date(anio, mes, 1).getDay() + 6) % 7;
        for (let i = 0; i < desplazamiento; i += 1) grilla.appendChild(celda('learner-calendar-day is-outside'));
        const diasMes = new Date(anio, mes + 1, 0).getDate();
        for (let dia = 1; dia <= diasMes; dia += 1) {
            const iso = aIso(anio, mes, dia);
            const registro = registros[iso];
            const etiqueta = registro ? registro.etiqueta || registro.estado : '';
            const boton = doc.createElement('button');
            boton.type = 'button';
            boton.className = 'learner-calendar-day';
            if (registro?.clase) boton.classList.add(`is-${registro.clase}`);
            if (hoy.getFullYear() === anio && hoy.getMonth() === mes && hoy.getDate() === dia) boton.classList.add('is-today');
            boton.setAttribute('role', 'gridcell');
            boton.setAttribute('aria-label', `${formatoFecha(iso)}: ${etiqueta || 'sin marcación'}`);
            const numero = doc.createElement('span');
            numero.className = 'learner-calendar-day-number';
            numero.textContent = String(dia);
            boton.appendChild(numero);
            if (registro) {
                const estado = doc.createElement('span');
                estado.className = 'learner-calendar-day-state';
                estado.textContent = etiqueta;
                boton.appendChild(estado);
            }
            boton.addEventListener('click', () => mostrarDetalle(iso, registro));
            grilla.appendChild(boton);
        }
    }

    function moverMes(delta) {
        visible.setMonth(visible.getMonth() + delta);
        dibujar();
    }

    calendario.querySelector('[data-learner-calendar-prev]').addEventListener('click', () => moverMes(-1));
    calendario.querySelector('[data-learner-calendar-next]').addEventListener('click', () => moverMes(1));
    dibujar();
    return { moverMes, mes: () => visible.getMonth(), anio: () => visible.getFullYear() };
}

/** Pestañas, filtros de evidencias, portafolio e inspector de la curva. */
function initPanelAprendiz(doc = document, win = window) {
    const raiz = doc.getElementById('panel-aprendiz-root');
    if (!raiz) return null;
    const claveTab = 'sena_learner_active_tab_' + (raiz.dataset.learnerId || '');
    const desplazar = elemento => elemento.scrollIntoView({ behavior: raiz.classList.contains('experience-reduced-motion') ? 'auto' : 'smooth', block: 'start' });
    const primeroDe = pestana => doc.querySelector(`[data-learner-tab="${pestana}"]`);

    // Portafolio digital (GitHub y Notion)
    const modal = doc.getElementById('portafolio-modal');
    const formulario = doc.getElementById('form-portafolio-aprendiz');
    const aviso = doc.getElementById('portafolio-feedback-msg');

    function abrirPortafolio(enfocar) {
        if (!modal) return;
        if (aviso) aviso.style.display = 'none';
        win.abrirModal(modal);
        const campo = enfocar ? doc.getElementById(`input-enlace-${enfocar}`) : null;
        if (campo) campo.focus();
    }

    function cerrarPortafolio() {
        if (modal) win.cerrarModal(modal);
    }

    const botonPortafolio = doc.getElementById('btn-open-portafolio-modal');
    if (botonPortafolio) botonPortafolio.addEventListener('click', () => abrirPortafolio());
    doc.querySelectorAll('.btn-open-portafolio-modal').forEach(boton => {
        boton.addEventListener('click', () => abrirPortafolio(boton.getAttribute('data-target-input')));
    });
    doc.querySelectorAll('[data-close-portafolio-modal]').forEach(boton => boton.addEventListener('click', cerrarPortafolio));
    if (modal) modal.addEventListener('click', evento => { if (evento.target === modal) cerrarPortafolio(); });

    async function guardarPortafolio(evento) {
        evento.preventDefault();
        const guardar = doc.getElementById('btn-save-portafolio');
        const texto = doc.getElementById('btn-save-portafolio-text');
        const datos = {
            enlace_github: doc.getElementById('input-enlace-github').value.trim(),
            enlace_notion: doc.getElementById('input-enlace-notion').value.trim(),
            csrf_token: formulario.querySelector('input[name="csrf_token"]').value,
        };
        if (guardar) guardar.disabled = true;
        if (texto) texto.textContent = 'Guardando...';
        if (aviso) aviso.style.display = 'none';
        try {
            const respuesta = await win.fetch(formulario.action, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', Accept: 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
                body: JSON.stringify(datos),
            });
            const cuerpo = await respuesta.json();
            if (!respuesta.ok || !cuerpo.ok) throw new Error(cuerpo.error || 'Error al guardar los enlaces.');
            win.location.reload();
        } catch (error) {
            if (aviso) {
                aviso.textContent = error.message || 'Error inesperado.';
                aviso.style.display = 'block';
            }
            if (guardar) guardar.disabled = false;
            if (texto) texto.textContent = 'Guardar enlaces';
        }
    }
    if (formulario) formulario.addEventListener('submit', guardarPortafolio);

    // Pestañas y vista continua
    const botonesTab = doc.querySelectorAll('.learner-tab-btn');
    const paneles = doc.querySelectorAll('[data-learner-tab]');

    function activarPestana(pestana, actualizarAncla = true) {
        botonesTab.forEach(boton => {
            const activa = boton.dataset.tabTarget === pestana;
            boton.classList.toggle('is-active', activa);
            boton.setAttribute('aria-selected', activa ? 'true' : 'false');
        });
        paneles.forEach(panel => panel.classList.toggle('tab-pane-active', panel.getAttribute('data-learner-tab') === pestana));
        if (actualizarAncla && win.history.replaceState) win.history.replaceState(null, null, '#tab-' + pestana);
        try { win.localStorage.setItem(claveTab, pestana); } catch (_) { /* La pestaña funciona sin almacenamiento local. */ }
        if (raiz.classList.contains('is-cascade-mode')) {
            const primero = primeroDe(pestana);
            if (primero) desplazar(primero);
        }
    }

    function avisarUbicacion(pestana) {
        win.dispatchEvent(new win.CustomEvent('learner:location', { detail: { tab: pestana, taskId: null } }));
    }

    botonesTab.forEach(boton => boton.addEventListener('click', () => activarPestana(boton.dataset.tabTarget, true)));

    doc.querySelectorAll('[data-jump-tab]').forEach(boton => {
        boton.addEventListener('click', () => {
            const pestana = boton.dataset.jumpTab;
            activarPestana(pestana, true);
            avisarUbicacion(pestana);
            const destino = boton.dataset.jumpTargetId ? doc.getElementById(boton.dataset.jumpTargetId) : primeroDe(pestana);
            if (destino) desplazar(destino);
        });
    });

    const textoVista = doc.getElementById('view-mode-text');
    function modoCascada(activo) {
        raiz.classList.toggle('is-cascade-mode', activo);
        if (textoVista) textoVista.textContent = activo ? 'Vista continua · Configurar' : 'Por pestañas · Configurar';
    }
    win.addEventListener('learner:preferences-applied', evento => modoCascada(evento.detail.preferences.viewMode === 'cascade'));

    doc.querySelectorAll('.learner-bottom-link').forEach(enlace => {
        enlace.addEventListener('click', () => {
            const pestana = PESTANA_POR_ANCLA[enlace.getAttribute('href')];
            if (pestana) {
                activarPestana(pestana, false);
                avisarUbicacion(pestana);
            }
        });
    });

    // Búsqueda y filtros de evidencias
    const busquedaInput = doc.getElementById('task-search-input');
    const limpiar = doc.getElementById('task-search-clear');
    const chips = doc.querySelectorAll('.task-chip');
    const evidencias = Array.from(doc.querySelectorAll('[data-task-item]'));
    const vacio = doc.getElementById('tasks-empty-filter-state');
    const entregadas = doc.querySelector('.entregadas-details');
    const tituloPendientes = doc.getElementById('heading-tareas-pendientes');
    let filtro = 'all';
    let busqueda = '';

    function aplicarFiltros() {
        if (!evidencias.length) return;
        let visibles = 0;
        let pendientesVisibles = 0;
        let entregadasVisibles = 0;
        evidencias.forEach(item => {
            const datos = datosEvidencia(item);
            const mostrar = coincideEvidencia(datos, filtro, busqueda);
            item.style.display = mostrar ? '' : 'none';
            if (!mostrar) return;
            visibles += 1;
            if (datos.estado === 'delivered') entregadasVisibles += 1;
            else pendientesVisibles += 1;
        });
        if (entregadas && (filtro === 'delivered' || (busqueda && entregadasVisibles > 0))) entregadas.open = true;
        if (tituloPendientes) tituloPendientes.style.display = (pendientesVisibles > 0 || filtro === 'all') ? '' : 'none';
        if (vacio) vacio.style.display = visibles === 0 ? 'block' : 'none';
    }

    function reiniciarFiltros() {
        if (busquedaInput) busquedaInput.value = '';
        busqueda = '';
        filtro = 'all';
        if (limpiar) limpiar.style.display = 'none';
        chips.forEach(chip => chip.classList.toggle('is-active', chip.dataset.taskFilter === 'all'));
        aplicarFiltros();
    }

    if (busquedaInput) {
        busquedaInput.addEventListener('input', evento => {
            busqueda = evento.target.value.toLowerCase().trim();
            if (limpiar) limpiar.style.display = busqueda ? 'block' : 'none';
            aplicarFiltros();
        });
    }
    if (limpiar) {
        limpiar.addEventListener('click', () => {
            if (busquedaInput) busquedaInput.value = '';
            busqueda = '';
            limpiar.style.display = 'none';
            aplicarFiltros();
        });
    }
    chips.forEach(chip => {
        chip.addEventListener('click', () => {
            chips.forEach(otro => otro.classList.toggle('is-active', otro === chip));
            filtro = chip.dataset.taskFilter;
            aplicarFiltros();
        });
    });
    const reiniciar = doc.getElementById('btn-reset-task-filters');
    if (reiniciar) reiniciar.addEventListener('click', reiniciarFiltros);

    // Los accesos del inicio revelan la evidencia aunque haya filtros o un acordeón cerrado.
    win.addEventListener('learner:navigate', evento => {
        const destino = evento.detail;
        activarPestana(destino.tab, true);
        let objetivo = primeroDe(destino.tab);
        if (destino.taskId) {
            reiniciarFiltros();
            objetivo = doc.getElementById('experiencia-tarea-' + destino.taskId) || objetivo;
            if (objetivo) {
                for (let padre = objetivo.parentElement; padre && padre !== raiz; padre = padre.parentElement) {
                    if (padre.tagName === 'DETAILS') padre.open = true;
                }
                objetivo.focus({ preventScroll: true });
            }
        }
        if (objetivo) desplazar(objetivo);
    });

    const conteo = contarChips(evidencias.map(datosEvidencia));
    Object.entries(CHIPS).forEach(([clave, id]) => {
        const elemento = doc.getElementById(id);
        if (elemento) elemento.textContent = conteo[clave];
    });

    // Inspector de la curva de rendimiento
    const inspector = {
        fecha: [doc.getElementById('inspector-fecha'), ''],
        puntaje: [doc.getElementById('inspector-puntaje'), ' pts'],
        asistencia: [doc.getElementById('inspector-asistencia'), '%'],
        evidencias: [doc.getElementById('inspector-evidencias'), '%'],
        estado: [doc.getElementById('inspector-estado'), ''],
    };
    function actualizarInspector(punto) {
        Object.entries(inspector).forEach(([campo, [elemento, sufijo]]) => {
            const valor = punto.getAttribute('data-' + campo);
            if (elemento && valor) elemento.textContent = valor + sufijo;
        });
    }
    doc.querySelectorAll('.curve-point-item').forEach(punto => {
        ['mouseenter', 'focus', 'click'].forEach(tipo => punto.addEventListener(tipo, () => actualizarInspector(punto)));
    });

    let guardada = null;
    try { guardada = win.localStorage.getItem(claveTab); } catch (_) { /* Sin preferencia guardada se abre el resumen. */ }
    activarPestana(pestanaInicial(win.location.hash, guardada), false);
    return { activarPestana, aplicarFiltros, modoCascada, actualizarInspector, filtro: () => filtro, busqueda: () => busqueda };
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = { pestanaInicial, aIso, formatoFecha, datosEvidencia, coincideEvidencia, contarChips, initCalendarioAsistencia, initPanelAprendiz };
}
if (typeof window !== 'undefined' && typeof document !== 'undefined') {
    window.panelAprendiz = initPanelAprendiz(document, window);
    window.calendarioAsistencia = initCalendarioAsistencia(document);
}
