/*
 * FiltroVista — utilidades compartidas para los filtros de la aplicación.
 *
 * Objetivos:
 *  1. Búsqueda uniforme: sin distinguir mayúsculas ni tildes y por varios términos.
 *  2. Posición de la vista estable: al filtrar, el usuario sigue viendo la lista
 *     que acaba de aparecer en lugar de ser enviado al inicio de la página.
 *
 * Filtros del cliente:  FiltroVista.aplicar(anclaDelFiltro, funcionQueFiltra)
 * Filtros del servidor: marcar el bloque con data-filter-region="<clave>";
 *                       el módulo recuerda la región y vuelve a ella tras recargar.
 */
(function () {
    'use strict';

    var CLAVE_RECARGA = 'filtro-vista:region';
    var MARGEN = 14;
    var usuarioMovioVista = false;

    function offsetSuperior() {
        var header = document.querySelector('.app-header');
        var alto = 0;
        if (header) {
            var posicion = window.getComputedStyle(header).position;
            if (posicion === 'sticky' || posicion === 'fixed') {
                alto = header.getBoundingClientRect().height;
            }
        }
        return alto + MARGEN;
    }

    function normalizar(texto) {
        return (texto === null || texto === undefined ? '' : String(texto))
            .toLocaleLowerCase('es')
            .normalize('NFD')
            .replace(/[\u0300-\u036f]/g, '');
    }

    // Convierte la consulta en términos normalizados; se exige que estén todos.
    function terminos(consulta) {
        return normalizar(consulta).split(/\s+/).filter(Boolean);
    }

    function coincide(texto, listaTerminos) {
        if (!listaTerminos || !listaTerminos.length) return true;
        var base = normalizar(texto);
        return listaTerminos.every(function (termino) {
            return base.indexOf(termino) !== -1;
        });
    }

    function estaVisible(el) {
        if (!el) return false;
        var rect = el.getBoundingClientRect();
        return rect.bottom > offsetSuperior() && rect.top < window.innerHeight;
    }

    function desplazarA(el, suave) {
        if (!el) return;
        var destino = window.pageYOffset + el.getBoundingClientRect().top - offsetSuperior();
        window.scrollTo({ top: Math.max(0, destino), behavior: suave ? 'smooth' : 'auto' });
    }

    function revelar(el, opciones) {
        if (!el || estaVisible(el)) return;
        desplazarA(el, !!(opciones && opciones.suave));
    }

    /*
     * Ejecuta `accion` (el filtrado real) conservando la posición de lectura:
     *  - Si el bloque de filtros estaba a la vista, se queda en el mismo punto de
     *    la pantalla aunque la lista se encoja o crezca.
     *  - Si estaba fuera de pantalla (el usuario había bajado por la lista vieja),
     *    la vista sube hasta él para mostrar el resultado desde el principio.
     */
    function aplicar(ancla, accion) {
        if (typeof accion !== 'function') return undefined;
        if (!ancla) return accion();

        var rectAntes = ancla.getBoundingClientRect();
        var topAntes = rectAntes.top;
        var visibleAntes = rectAntes.bottom > offsetSuperior() && rectAntes.top < window.innerHeight;
        var resultado = accion();

        var ajustar = function () {
            var rectAhora = ancla.getBoundingClientRect();
            if (visibleAntes) {
                var delta = rectAhora.top - topAntes;
                if (Math.abs(delta) > 1) {
                    window.scrollTo({ top: Math.max(0, window.pageYOffset + delta), behavior: 'auto' });
                }
                // Si el ancla quedó por arriba del encabezado por colapso de altura, re-encuadrarla
                if (ancla.getBoundingClientRect().top < offsetSuperior()) {
                    desplazarA(ancla, false);
                }
            } else {
                desplazarA(ancla, false);
            }
        };

        if (window.requestAnimationFrame) {
            window.requestAnimationFrame(ajustar);
            setTimeout(ajustar, 50);
        } else {
            ajustar();
        }
        return resultado;
    }

    // ── Filtros que recargan la página (formularios GET, chips, enlaces) ──

    function claveRegion(region) {
        if (!region) return '';
        if (region.getAttribute('data-filter-region')) return region.getAttribute('data-filter-region');
        if (region.id) return region.id;
        if (region.classList.contains('estado-chips')) return 'estado-chips';
        if (region.classList.contains('period-tabs')) return 'period-tabs';
        if (region.classList.contains('filtros-observador')) return 'filtros-observador';
        if (region.classList.contains('table-toolbar')) return 'table-toolbar';
        if (region.classList.contains('followup-filters')) return 'followup-filters';
        return '';
    }

    function recordar(region) {
        if (!region) return;
        var clave = claveRegion(region);
        if (!clave) return;
        try {
            sessionStorage.setItem(CLAVE_RECARGA, JSON.stringify({
                ruta: window.location.pathname,
                clave: clave,
                timestamp: Date.now()
            }));
        } catch (e) { /* almacenamiento no disponible */ }
    }

    function leerRegionPendiente() {
        var crudo = null;
        try {
            crudo = sessionStorage.getItem(CLAVE_RECARGA);
            sessionStorage.removeItem(CLAVE_RECARGA);
        } catch (e) { return null; }
        if (!crudo) return null;
        try {
            var dato = JSON.parse(crudo);
            if (!dato || dato.ruta !== window.location.pathname) return null;
            // Expirar si pasaron más de 5 minutos
            if (dato.timestamp && (Date.now() - dato.timestamp > 300000)) return null;
            return dato.clave;
        } catch (e) { return null; }
    }

    function buscarRegion(clave) {
        if (!clave) return null;
        var porAtributo = document.querySelector('[data-filter-region="' + clave.replace(/"/g, '\\"') + '"]');
        if (porAtributo) return porAtributo;
        var porId = document.getElementById(clave);
        if (porId) return porId;
        try {
            var porClase = document.querySelector('.' + clave);
            if (porClase) return porClase;
        } catch (e) {}
        return null;
    }

    function restaurarTrasRecarga() {
        // Un ancla explícita en la URL manda sobre la restauración automática.
        if (window.location.hash) return;
        var clave = leerRegionPendiente();
        if (!clave) return;
        var region = buscarRegion(clave);
        if (!region) return;

        var reencuadrar = function () {
            if (usuarioMovioVista) return;
            desplazarA(region, false);
        };
        reencuadrar();
        // Fuentes e imágenes tardías pueden mover el bloque: se reencuadra al terminar.
        window.addEventListener('load', function () { setTimeout(reencuadrar, 0); }, { once: true });
        setTimeout(reencuadrar, 150);
        setTimeout(reencuadrar, 400);
    }

    function marcarInteraccion() { usuarioMovioVista = true; }

    ['wheel', 'touchmove', 'keydown', 'mousedown'].forEach(function (evento) {
        window.addEventListener(evento, marcarInteraccion, { passive: true });
    });

    function regionDe(el) {
        return el && el.closest ? el.closest('[data-filter-region], .estado-chips, .period-tabs, .filtros-observador, .table-toolbar, .followup-filters, form[method="GET"], form[method="get"]') : null;
    }

    document.addEventListener('submit', function (ev) {
        recordar(regionDe(ev.target));
    }, true);

    // Cubre los selectores con onchange="this.form.submit()", que no disparan submit.
    document.addEventListener('change', function (ev) {
        var control = ev.target;
        if (!control || !control.closest) return;
        if (!control.matches('select, input[type="date"], input[type="radio"], input[type="checkbox"]')) return;
        recordar(regionDe(control));
    }, true);

    document.addEventListener('click', function (ev) {
        var enlace = ev.target && ev.target.closest ? ev.target.closest('a[href]') : null;
        if (!enlace) return;
        if (enlace.target === '_blank' || enlace.hasAttribute('download')) return;
        var href = enlace.getAttribute('href') || '';
        if (href.charAt(0) === '#') return;
        recordar(regionDe(enlace));
    }, true);

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', restaurarTrasRecarga);
    } else {
        restaurarTrasRecarga();
    }

    window.FiltroVista = {
        normalizar: normalizar,
        terminos: terminos,
        coincide: coincide,
        offsetSuperior: offsetSuperior,
        estaVisible: estaVisible,
        desplazarA: desplazarA,
        revelar: revelar,
        aplicar: aplicar,
        recordar: recordar
    };
})();
