(function (window, document) {
    'use strict';

    const SELECTOR_MODAL_ABIERTO = 'dialog[open], .app-modal-overlay.is-open, [role="dialog"].is-open, .pl-modal-backdrop.is-open, .pl-modal-raps.is-open';
    const SELECTOR_FOCOS = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
    const focosDeRetorno = new WeakMap();
    const estadosOcultos = new WeakMap();
    const enviosAprobados = new WeakSet();
    let activadorPendiente = null;
    let confirmacionPendiente = null;

    function resolverModal(referencia) {
        return typeof referencia === 'string' ? document.getElementById(referencia) : referencia;
    }

    function esDialogoNativo(modal) {
        return Boolean(modal && modal.tagName && modal.tagName.toLowerCase() === 'dialog' && typeof modal.showModal === 'function');
    }

    function estaAbierto(modal) {
        if (!modal || modal.hidden) return false;
        return esDialogoNativo(modal) ? modal.open : Boolean(modal.classList && modal.classList.contains('is-open'));
    }

    function obtenerModalesAbiertos() {
        return Array.from(document.querySelectorAll(SELECTOR_MODAL_ABIERTO)).filter(estaAbierto);
    }

    function sincronizarBloqueoFondo() {
        document.body.classList.toggle('modal-open', obtenerModalesAbiertos().length > 0);
    }

    function elementosEnfocables(modal) {
        return Array.from(modal.querySelectorAll(SELECTOR_FOCOS)).filter(function (elemento) {
            if (elemento.disabled || elemento.hidden || elemento.getAttribute('aria-hidden') === 'true') return false;
            return typeof elemento.getClientRects !== 'function' || elemento.getClientRects().length > 0;
        });
    }

    function enfocarInicio(modal) {
        const destino = modal.querySelector('[autofocus]') || elementosEnfocables(modal)[0] || modal;
        if (destino === modal && !modal.hasAttribute('tabindex')) modal.setAttribute('tabindex', '-1');
        if (typeof destino.focus === 'function') destino.focus();
    }

    function recordarFoco(modal) {
        if (focosDeRetorno.has(modal)) return;
        const controles = (activadorPendiente && activadorPendiente.getAttribute('aria-controls') || '').split(/\s+/);
        const activadorRelacionado = activadorPendiente && (!controles[0] || controles.includes(modal.id));
        focosDeRetorno.set(modal, activadorRelacionado ? activadorPendiente : document.activeElement);
        estadosOcultos.set(modal, Boolean(modal.hidden));
    }

    function devolverFoco(modal) {
        const destino = focosDeRetorno.get(modal);
        focosDeRetorno.delete(modal);
        estadosOcultos.delete(modal);
        if (destino && destino.isConnected !== false && typeof destino.focus === 'function') destino.focus();
    }

    function abrirModal(referencia) {
        const modal = resolverModal(referencia);
        if (!modal) return false;
        recordarFoco(modal);

        if (esDialogoNativo(modal)) {
            if (!modal.open) modal.showModal();
        } else {
            modal.hidden = false;
            modal.classList.add('is-open');
            modal.setAttribute('aria-hidden', 'false');
            if (modal.tagName && modal.tagName.toLowerCase() === 'dialog') modal.setAttribute('open', '');
        }

        sincronizarBloqueoFondo();
        if (!modal.contains(document.activeElement)) enfocarInicio(modal);
        return true;
    }

    function cerrarModal(referencia, valorRetorno) {
        const modal = resolverModal(referencia);
        if (!estaAbierto(modal) || modal.classList && modal.classList.contains('is-loading')) return false;

        if (esDialogoNativo(modal)) {
            modal.close(valorRetorno || '');
        } else {
            modal.classList.remove('is-open');
            modal.setAttribute('aria-hidden', 'true');
            if (modal.tagName && modal.tagName.toLowerCase() === 'dialog') modal.removeAttribute('open');
            modal.hidden = Boolean(estadosOcultos.get(modal));
        }

        sincronizarBloqueoFondo();
        devolverFoco(modal);
        return true;
    }

    function manejarCierre(evento) {
        const modal = evento.target;
        if (!modal || !esDialogoNativo(modal)) return;
        sincronizarBloqueoFondo();
        devolverFoco(modal);
        if (modal.id === 'modal-confirmacion' && confirmacionPendiente) {
            const pendiente = confirmacionPendiente;
            confirmacionPendiente = null;
            pendiente.resolve(modal.returnValue === 'confirmar');
        }
    }

    function manejarTeclado(evento) {
        const modales = obtenerModalesAbiertos();
        const modal = modales[modales.length - 1];
        if (!modal) return;

        if (evento.key === 'Escape' && !esDialogoNativo(modal)) {
            evento.preventDefault();
            cerrarModal(modal);
            return;
        }
        if (evento.key !== 'Tab' || esDialogoNativo(modal)) return;

        const elementos = elementosEnfocables(modal);
        if (!elementos.length) {
            evento.preventDefault();
            enfocarInicio(modal);
            return;
        }

        const primero = elementos[0];
        const ultimo = elementos[elementos.length - 1];
        if (evento.shiftKey && (document.activeElement === primero || !modal.contains(document.activeElement))) {
            evento.preventDefault();
            ultimo.focus();
        } else if (!evento.shiftKey && (document.activeElement === ultimo || !modal.contains(document.activeElement))) {
            evento.preventDefault();
            primero.focus();
        }
    }

    function manejarClic(evento) {
        const objetivo = evento.target;
        const aceptador = objetivo.closest && objetivo.closest('[data-confirm-accept]') || objetivo.dataset && objetivo.dataset.confirmAccept !== undefined && objetivo;
        const cancelador = objetivo.closest && objetivo.closest('[data-confirm-cancel]') || objetivo.dataset && objetivo.dataset.confirmCancel !== undefined && objetivo;
        if (aceptador) {
            cerrarModal('modal-confirmacion', 'confirmar');
            return;
        }
        if (cancelador) {
            cerrarModal('modal-confirmacion', 'cancelar');
            return;
        }

        const modal = objetivo;
        if (estaAbierto(modal) && obtenerModalesAbiertos().includes(modal) && !(modal.classList && modal.classList.contains('is-loading')) && modal.dataset.backdropClose !== 'false') {
            cerrarModal(modal);
        }
        sincronizarBloqueoFondo();
    }

    function manejarClicPrevio(evento) {
        activadorPendiente = evento.target.closest && evento.target.closest('[aria-haspopup="dialog"][aria-controls]') || evento.target;
    }

    function registrarAperturasDirectas() {
        obtenerModalesAbiertos().forEach(function (modal) {
            recordarFoco(modal);
            if (!esDialogoNativo(modal) && !modal.contains(document.activeElement)) enfocarInicio(modal);
        });
        activadorPendiente = null;
        sincronizarBloqueoFondo();
    }

    function leerOpcionesConfirmacion(formulario, enviador) {
        const fuenteMensaje = enviador && enviador.dataset && enviador.dataset.confirm !== undefined
            ? enviador
            : formulario;
        const datosBoton = enviador && enviador.dataset || {};
        const datosFormulario = formulario.dataset || {};
        const mensaje = fuenteMensaje && fuenteMensaje.dataset && fuenteMensaje.dataset.confirm;
        if (!mensaje) return null;
        return {
            message: mensaje,
            title: datosBoton.confirmTitle || datosFormulario.confirmTitle || 'Confirme esta acción',
            confirmLabel: datosBoton.confirmLabel || datosFormulario.confirmLabel || 'Continuar',
            intent: datosBoton.confirmIntent || datosFormulario.confirmIntent || 'default',
        };
    }

    function confirmarAccion(mensaje, opciones) {
        return new Promise(function (resolve) {
            const modal = document.getElementById('modal-confirmacion');
            if (!modal) {
                resolve(false);
                return;
            }
            if (confirmacionPendiente) {
                const anterior = confirmacionPendiente;
                confirmacionPendiente = null;
                anterior.resolve(false);
                if (modal.open) modal.close('cancelar');
            }

            const ajustes = opciones || {};
            const titulo = modal.querySelector('[data-confirm-title]');
            const texto = modal.querySelector('[data-confirm-message]');
            const aceptar = modal.querySelector('[data-confirm-accept]');
            if (titulo) titulo.textContent = ajustes.title || 'Confirme esta acción';
            if (texto) texto.textContent = mensaje;
            if (aceptar) aceptar.textContent = ajustes.confirmLabel || 'Continuar';
            modal.classList.toggle('is-danger', ajustes.intent === 'danger');
            modal.classList.toggle('is-warning', ajustes.intent === 'warning');
            modal.returnValue = '';
            confirmacionPendiente = { resolve };
            abrirModal(modal);
        });
    }

    function confirmarYEnviarFormulario(formulario, mensaje, opciones, enviador) {
        if (!formulario || typeof formulario.requestSubmit !== 'function') return Promise.resolve(false);
        return confirmarAccion(mensaje, opciones).then(function (confirmado) {
            if (!confirmado || formulario.isConnected === false) return false;
            enviosAprobados.add(formulario);
            try {
                if (enviador) formulario.requestSubmit(enviador);
                else formulario.requestSubmit();
                return true;
            } catch (error) {
                enviosAprobados.delete(formulario);
                return false;
            }
        });
    }

    function mostrarAviso(mensaje, opciones) {
        const ajustes = opciones || {};
        let region = document.getElementById('avisos-emergentes');
        if (!region) {
            region = document.createElement('div');
            region.id = 'avisos-emergentes';
            region.classList.add('app-notice-region');
            region.setAttribute('role', 'region');
            region.setAttribute('aria-label', 'Avisos de la aplicación');
            region.setAttribute('aria-live', 'polite');
            region.setAttribute('aria-relevant', 'additions text');
            document.body.appendChild(region);
        }

        const aviso = document.createElement('section');
        aviso.classList.add('app-notice');
        if (ajustes.intent) aviso.classList.add('is-' + ajustes.intent);
        aviso.setAttribute('role', ajustes.intent === 'danger' ? 'alert' : 'status');

        const contenido = document.createElement('div');
        contenido.classList.add('app-notice-copy');
        if (ajustes.title) {
            const titulo = document.createElement('strong');
            titulo.textContent = ajustes.title;
            contenido.appendChild(titulo);
        }
        const texto = document.createElement('p');
        texto.textContent = mensaje;
        contenido.appendChild(texto);

        const cerrar = document.createElement('button');
        cerrar.type = 'button';
        cerrar.classList.add('app-notice-close');
        cerrar.setAttribute('aria-label', 'Cerrar aviso');
        cerrar.textContent = '×';
        cerrar.addEventListener('click', function () { aviso.remove(); });

        aviso.appendChild(contenido);
        aviso.appendChild(cerrar);
        region.appendChild(aviso);
        window.setTimeout(function () { aviso.remove(); }, Number(ajustes.duration) || 6000);
        return aviso;
    }

    function manejarEnvio(evento) {
        const formulario = evento.target;
        if (!formulario || formulario.tagName !== 'FORM') return;
        if (enviosAprobados.has(formulario)) {
            enviosAprobados.delete(formulario);
            return;
        }
        const opciones = leerOpcionesConfirmacion(formulario, evento.submitter);
        if (!opciones) return;
        evento.preventDefault();
        confirmarYEnviarFormulario(formulario, opciones.message, opciones, evento.submitter);
    }

    document.addEventListener('click', manejarClicPrevio, true);
    document.addEventListener('click', manejarClic);
    document.addEventListener('click', registrarAperturasDirectas);
    document.addEventListener('keydown', manejarTeclado);
    document.addEventListener('submit', manejarEnvio, true);
    document.addEventListener('close', manejarCierre, true);

    window.abrirModal = abrirModal;
    window.cerrarModal = cerrarModal;
    window.confirmarAccion = confirmarAccion;
    window.confirmarYEnviarFormulario = confirmarYEnviarFormulario;
    window.mostrarAviso = mostrarAviso;
    window.ModalSystem = {
        open: abrirModal,
        close: cerrarModal,
        syncBodyLock: sincronizarBloqueoFondo,
    };
})(window, document);
