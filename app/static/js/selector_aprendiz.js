(function (ambito, crearApi) {
    'use strict';

    const api = crearApi();
    if (typeof module === 'object' && module.exports) module.exports = api;
    ambito.SelectorAprendiz = api;

    if (ambito.document) {
        api.inicializar(ambito.document, ambito.crypto);
    }
})(globalThis, function () {
    'use strict';

    const RANGO_UINT32 = 0x100000000;

    function numeroAleatorioSeguro(limite, cryptoApi = globalThis.crypto) {
        if (!Number.isSafeInteger(limite) || limite < 1 || limite > RANGO_UINT32) {
            throw new RangeError('El límite debe ser un entero entre 1 y 2³².');
        }
        if (limite === 1) return 0;
        if (!cryptoApi || typeof cryptoApi.getRandomValues !== 'function') {
            throw new Error('Este navegador no ofrece un generador aleatorio criptográfico.');
        }

        const cantidadUniforme = Math.floor(RANGO_UINT32 / limite) * limite;
        const valor = new Uint32Array(1);
        do {
            cryptoApi.getRandomValues(valor);
        } while (valor[0] >= cantidadUniforme);
        return valor[0] % limite;
    }

    function barajarAprendices(aprendices, elegirIndice = numeroAleatorioSeguro) {
        const resultado = aprendices.slice();
        for (let indice = resultado.length - 1; indice > 0; indice -= 1) {
            const otroIndice = elegirIndice(indice + 1);
            if (!Number.isInteger(otroIndice) || otroIndice < 0 || otroIndice > indice) {
                throw new RangeError('El generador devolvió un índice fuera del rango permitido.');
            }
            [resultado[indice], resultado[otroIndice]] = [resultado[otroIndice], resultado[indice]];
        }
        return resultado;
    }

    function crearBolsa(aprendices, elegirIndice = numeroAleatorioSeguro) {
        if (!Array.isArray(aprendices) || aprendices.length === 0) {
            throw new RangeError('Se necesita al menos un aprendiz para iniciar el sorteo.');
        }
        const identificadores = new Set();
        for (const aprendiz of aprendices) {
            if (!aprendiz || aprendiz.id === undefined || aprendiz.id === null || identificadores.has(String(aprendiz.id))) {
                throw new Error('La lista debe tener identificadores únicos para cada aprendiz.');
            }
            identificadores.add(String(aprendiz.id));
        }

        const participantes = aprendices.slice();
        let pendientes = [];
        let ultimoIdentificador = null;

        return {
            siguiente() {
                if (pendientes.length === 0) {
                    pendientes = barajarAprendices(participantes, elegirIndice);
                    if (pendientes.length > 1 && String(pendientes[pendientes.length - 1].id) === ultimoIdentificador) {
                        const otroIndice = elegirIndice(pendientes.length - 1);
                        if (!Number.isInteger(otroIndice) || otroIndice < 0 || otroIndice >= pendientes.length - 1) {
                            throw new RangeError('El generador devolvió un índice fuera del rango permitido.');
                        }
                        const ultimoIndice = pendientes.length - 1;
                        [pendientes[ultimoIndice], pendientes[otroIndice]] = [pendientes[otroIndice], pendientes[ultimoIndice]];
                    }
                }
                const seleccionado = pendientes.pop();
                ultimoIdentificador = String(seleccionado.id);
                return seleccionado;
            },
            restantes() {
                return pendientes.length;
            },
        };
    }

    function inicializar(documento = globalThis.document, cryptoApi = globalThis.crypto) {
        if (!documento) return null;
        const panel = documento.getElementById('selector-aprendiz');
        if (!panel) return null;

        const botonSortear = documento.getElementById('selector-aprendiz-sortear');
        const botonExpandir = documento.getElementById('selector-aprendiz-expandir');
        const botonSalir = documento.getElementById('selector-aprendiz-salir');
        const nombreResultado = documento.getElementById('selector-aprendiz-nombre');
        const estadoResultado = documento.getElementById('selector-aprendiz-estado');
        const mensaje = documento.getElementById('selector-aprendiz-mensaje');
        const contador = documento.getElementById('selector-aprendiz-contador');
        if (!botonSortear || !nombreResultado || !mensaje) return null;

        const participantes = Array.from(documento.querySelectorAll('[data-selector-aprendiz]'), elemento => ({
            id: elemento.dataset.id,
            nombre: elemento.dataset.nombre,
            estado: elemento.dataset.estado,
        }));

        if (participantes.length === 0) {
            botonSortear.disabled = true;
            mensaje.textContent = 'No hay aprendices activos disponibles para participar.';
            if (contador) contador.textContent = '0 participantes';
            return { cantidad: 0 };
        }

        const bolsa = crearBolsa(participantes, limite => numeroAleatorioSeguro(limite, cryptoApi));
        let sorteando = false;
        let pantallaAlterna = false;
        const temporizador = documento.defaultView?.setTimeout?.bind(documento.defaultView) || globalThis.setTimeout;

        if (contador) {
            contador.textContent = participantes.length === 1
                ? '1 participante disponible'
                : `${participantes.length} participantes disponibles`;
        }

        botonSortear.addEventListener('click', () => {
            if (sorteando) return;
            sorteando = true;
            botonSortear.disabled = true;
            panel.setAttribute('aria-busy', 'true');
            panel.classList.add('is-sorting');
            mensaje.textContent = 'Sorteando el próximo turno…';
            nombreResultado.textContent = 'Preparando el sorteo';
            if (estadoResultado) estadoResultado.textContent = '';

            temporizador(() => {
                let seleccionado;
                try {
                    seleccionado = bolsa.siguiente();
                } catch (_error) {
                    panel.classList.remove('is-sorting');
                    panel.setAttribute('aria-busy', 'false');
                    botonSortear.disabled = false;
                    mensaje.textContent = 'No fue posible completar el sorteo seguro. Revisa el navegador y vuelve a intentarlo.';
                    nombreResultado.textContent = 'Sorteo no disponible';
                    sorteando = false;
                    return;
                }
                nombreResultado.textContent = seleccionado.nombre;
                if (estadoResultado) estadoResultado.textContent = seleccionado.estado;
                panel.classList.remove('is-sorting');
                panel.classList.add('has-selection');
                panel.setAttribute('aria-busy', 'false');
                botonSortear.disabled = false;
                botonSortear.textContent = bolsa.restantes() === 0 ? 'Iniciar otra ronda' : 'Sortear otro aprendiz';
                mensaje.textContent = bolsa.restantes() === 0
                    ? 'Ronda completa: todos participaron. Puedes iniciar una nueva ronda.'
                    : `Turno asignado. Quedan ${bolsa.restantes()} ${bolsa.restantes() === 1 ? 'aprendiz' : 'aprendices'} por participar en esta ronda.`;
                sorteando = false;
            }, 900);
        });

        function actualizarPantallaCompleta() {
            const estabaPantallaCompleta = botonSalir && !botonSalir.hidden;
            const pantallaCompleta = documento.fullscreenElement === panel || pantallaAlterna;
            panel.classList.toggle('is-fullscreen-fallback', pantallaAlterna);
            documento.body?.classList.toggle('selector-aprendiz-sin-desplazamiento', pantallaAlterna);
            if (botonExpandir) botonExpandir.hidden = pantallaCompleta;
            if (botonSalir) botonSalir.hidden = !pantallaCompleta;
            if (pantallaCompleta && botonSalir) botonSalir.focus();
            else if (estabaPantallaCompleta && botonExpandir) botonExpandir.focus();
        }

        async function abrirPantallaCompleta() {
            if (typeof panel.requestFullscreen === 'function') {
                try {
                    await panel.requestFullscreen();
                    actualizarPantallaCompleta();
                    return;
                } catch (_error) {
                    pantallaAlterna = true;
                }
            } else {
                pantallaAlterna = true;
            }
            actualizarPantallaCompleta();
        }

        async function salirDePantallaCompleta() {
            if (documento.fullscreenElement && typeof documento.exitFullscreen === 'function') {
                try {
                    await documento.exitFullscreen();
                } catch (_error) {
                    pantallaAlterna = false;
                }
            }
            pantallaAlterna = false;
            actualizarPantallaCompleta();
        }

        botonExpandir?.addEventListener('click', abrirPantallaCompleta);
        botonSalir?.addEventListener('click', salirDePantallaCompleta);
        documento.addEventListener('fullscreenchange', actualizarPantallaCompleta);
        documento.addEventListener('keydown', evento => {
            if (evento.key === 'Escape' && pantallaAlterna) salirDePantallaCompleta();
        });

        return { cantidad: participantes.length, bolsa };
    }

    return { barajarAprendices, crearBolsa, inicializar, numeroAleatorioSeguro };
});
