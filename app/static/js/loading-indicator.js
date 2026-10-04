(function () {
    const indicador = document.getElementById('app-loading-overlay');
    if (!indicador) return;

    let solicitudesHtmxActivas = 0;

    function mostrarIndicador() {
        indicador.hidden = false;
        indicador.setAttribute('aria-hidden', 'false');
        document.body.setAttribute('aria-busy', 'true');
    }

    function ocultarIndicador() {
        indicador.hidden = true;
        indicador.setAttribute('aria-hidden', 'true');
        document.body.setAttribute('aria-busy', 'false');
    }

    function esDestinoInterno(url) {
        let destino;
        try {
            destino = new URL(url, window.location.href);
        } catch (error) {
            return false;
        }

        if (destino.origin !== window.location.origin) return false;
        if (destino.hash && destino.pathname === window.location.pathname
            && destino.search === window.location.search) return false;
        const ruta = destino.pathname;
        return !ruta.includes('/descargar')
            && !/\/archivo(?:\/|$)/.test(ruta)
            && !ruta.includes('/logout')
            && !ruta.includes('/exportar')
            && !ruta.includes('/plantilla');
    }

    function debeIndicarEnlace(evento, enlace) {
        if (!enlace || evento.defaultPrevented || evento.button !== 0) return false;
        if (evento.ctrlKey || evento.metaKey || evento.shiftKey || evento.altKey) return false;
        if (enlace.target && enlace.target !== '_self') return false;
        if (enlace.hasAttribute('download') || enlace.hasAttribute('data-no-loading')) return false;
        if (enlace.getAttribute('hx-boost') === 'false') return false;

        const href = enlace.getAttribute('href');
        if (!href || href.startsWith('#') || href.startsWith('javascript:')) return false;
        return esDestinoInterno(enlace.href);
    }

    function debeIndicarFormulario(evento, formulario) {
        if (!formulario || evento.defaultPrevented) return false;
        if (formulario.target && formulario.target !== '_self') return false;
        if (formulario.getAttribute('method')?.toLowerCase() === 'dialog') return false;
        if (formulario.hasAttribute('data-no-loading')) return false;
        if (formulario.getAttribute('hx-boost') === 'false') return false;
        return esDestinoInterno(formulario.action || window.location.href);
    }

    function debeIndicarHtmx(evento) {
        if (!evento || evento.defaultPrevented) return false;
        const elemento = evento.detail?.elt || evento.target;
        if (!elemento || typeof elemento.getAttribute !== 'function') return true;

        if (elemento.hasAttribute('data-no-loading')) return false;
        if (elemento.getAttribute('hx-boost') === 'false') return false;
        if (elemento.hasAttribute('hx-indicator')) return false;
        const trigger = elemento.getAttribute('hx-trigger') || '';
        if (/\bevery\b/i.test(trigger)) return false;
        if (typeof elemento.closest === 'function') {
            const ancestroExcluido = elemento.closest('[data-no-loading], [hx-indicator], [hx-trigger*="every"]');
            if (ancestroExcluido) return false;
        }
        return true;
    }

    function programarIndicador(evento) {
        queueMicrotask(function () {
            if (!evento.defaultPrevented) mostrarIndicador();
        });
    }

    function alHacerClic(evento) {
        const enlace = evento.target?.closest?.('a[href]');
        if (debeIndicarEnlace(evento, enlace)) programarIndicador(evento);
    }

    function alEnviarFormulario(evento) {
        const formulario = evento.target?.closest?.('form');
        if (debeIndicarFormulario(evento, formulario)) programarIndicador(evento);
    }

    function alIniciarSolicitudHtmx(evento) {
        queueMicrotask(function () {
            if (!debeIndicarHtmx(evento)) return;
            if (evento.detail && typeof evento.detail === 'object') {
                evento.detail._indicaCarga = true;
            }
            solicitudesHtmxActivas += 1;
            mostrarIndicador();
        });
    }

    function alFinalizarSolicitudHtmx(evento) {
        if (evento && evento.detail && typeof evento.detail === 'object' && !evento.detail._indicaCarga) {
            return;
        }
        solicitudesHtmxActivas = Math.max(0, solicitudesHtmxActivas - 1);
        if (solicitudesHtmxActivas === 0) ocultarIndicador();
    }

    function alVolverAPagina() {
        solicitudesHtmxActivas = 0;
        ocultarIndicador();
    }

    document.addEventListener('click', alHacerClic);
    document.addEventListener('submit', alEnviarFormulario);
    document.addEventListener('htmx:beforeRequest', alIniciarSolicitudHtmx);
    document.addEventListener('htmx:afterRequest', alFinalizarSolicitudHtmx);
    window.addEventListener('pageshow', alVolverAPagina);

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', ocultarIndicador, { once: true });
    } else {
        ocultarIndicador();
    }
})();
