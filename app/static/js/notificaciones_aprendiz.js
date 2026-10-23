'use strict';

function claveServidorPush(valor, win = window) {
    const relleno = '='.repeat((4 - valor.length % 4) % 4);
    const base64 = (valor + relleno).replace(/-/g, '+').replace(/_/g, '/');
    const binario = win.atob(base64);
    const bytes = new Uint8Array(binario.length);
    for (let indice = 0; indice < binario.length; indice += 1) bytes[indice] = binario.charCodeAt(indice);
    return bytes;
}

function crearControlNotificacionesAprendiz(root, win = window, doc = document) {
    const cursorInicial = Number.parseInt(root.dataset.notificationCursor || '0', 10);
    let cursor = Number.isFinite(cursorInicial) && cursorInicial > 0 ? cursorInicial : 0;
    let audio = null;
    let sonidoActivo = false;
    let suscripcion = null;
    const vistos = new Set();
    const live = root.querySelector('[data-notification-live]');
    const estado = root.querySelector('[data-notification-status]');
    const botonSonido = root.querySelector('[data-enable-notification-sound]');
    const botonPush = root.querySelector('[data-toggle-push]');
    const experiencia = doc.getElementById('panel-aprendiz-root');
    const centro = doc.querySelector('.learner-notifications');

    function modoSilencioso() {
        return (experiencia?.dataset.experienceNotificationMode || centro?.dataset.notificationMode || 'all') === 'quiet';
    }

    function informar(texto) {
        if (estado) estado.textContent = texto;
    }

    function reproducirTono() {
        if (!sonidoActivo || modoSilencioso() || !audio) return;
        const oscillator = audio.createOscillator();
        const volumen = audio.createGain();
        oscillator.frequency.value = 660;
        volumen.gain.value = 0.035;
        oscillator.connect(volumen);
        volumen.connect(audio.destination);
        oscillator.start();
        oscillator.stop(audio.currentTime + 0.16);
    }

    function anunciar(notificacion) {
        if (!live || vistos.has(notificacion.id)) return;
        vistos.add(notificacion.id);
        const aviso = doc.createElement('div');
        aviso.className = 'learner-notification-toast';
        const texto = doc.createElement('p');
        texto.textContent = notificacion.mensaje;
        aviso.appendChild(texto);
        if (typeof notificacion.url === 'string' && /^\/aprendiz\/\d+\/notificaciones(?:#.*)?$/.test(notificacion.url)) {
            const enlace = doc.createElement('a');
            enlace.href = notificacion.url;
            enlace.textContent = 'Abrir notificaciones';
            aviso.appendChild(enlace);
        }
        live.appendChild(aviso);
        reproducirTono();
    }

    async function consultarNuevas() {
        const base = root.dataset.notificationPollUrl;
        if (!base) return;
        const separador = base.includes('?') ? '&' : '?';
        try {
            const respuesta = await win.fetch(`${base}${separador}desde_id=${cursor}`, {
                credentials: 'same-origin', headers: { Accept: 'application/json' },
            });
            if (!respuesta.ok) throw new Error('No fue posible consultar los avisos.');
            const datos = await respuesta.json();
            for (const notificacion of Array.isArray(datos.notificaciones) ? datos.notificaciones : []) {
                const id = Number(notificacion.id);
                if (!Number.isInteger(id) || id <= 0) continue;
                cursor = Math.max(cursor, id);
                if (['calificacion', 'juicio_evaluativo'].includes(notificacion.tipo)) anunciar(notificacion);
            }
        } catch (_) {
            informar('No se pudieron actualizar los avisos. Se volverán a consultar automáticamente.');
        }
    }

    async function activarSonido() {
        const Audio = win.AudioContext || win.webkitAudioContext;
        if (!Audio) {
            informar('Este navegador no admite sonido en la página. Los avisos de texto siguen activos.');
            return false;
        }
        audio = audio || new Audio();
        try {
            await audio.resume();
            sonidoActivo = true;
            informar(modoSilencioso()
                ? 'El sonido está activado, pero «Lectura tranquila» mantiene los avisos en silencio.'
                : 'El sonido acompañará los avisos mientras esta página esté abierta.');
            return true;
        } catch (_) {
            informar('El navegador no permitió activar el sonido. Los avisos de texto siguen activos.');
            return false;
        }
    }

    function pushDisponible() {
        return Boolean(root.dataset.pushEnabled === 'true'
            && win.Notification && win.navigator?.serviceWorker
            && win.PushManager && root.dataset.vapidPublicKey);
    }

    async function actualizarSuscripcion() {
        if (!pushDisponible()) {
            informar('Los avisos del navegador no están disponibles en este dispositivo.');
            return false;
        }
        try {
            const permiso = await win.Notification.requestPermission();
            if (permiso !== 'granted') {
                informar(permiso === 'denied'
                    ? 'El permiso está desactivado en el navegador. Los avisos del panel siguen activos.'
                    : 'No se concedió el permiso. Los avisos del panel siguen activos.');
                return false;
            }
            const registro = await win.navigator.serviceWorker.register(root.dataset.serviceWorkerUrl, { scope: '/aprendiz/' });
            suscripcion = await registro.pushManager.getSubscription();
            if (!suscripcion) {
                suscripcion = await registro.pushManager.subscribe({
                    userVisibleOnly: true,
                    applicationServerKey: claveServidorPush(root.dataset.vapidPublicKey, win),
                });
            }
            const respuesta = await win.fetch(root.dataset.subscriptionUrl, {
                method: 'POST', credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': root.dataset.csrfToken },
                body: JSON.stringify(suscripcion.toJSON()),
            });
            if (!respuesta.ok) throw new Error('No se pudo guardar la suscripción.');
            if (botonPush) botonPush.textContent = 'Desactivar avisos del navegador';
            informar('Los avisos del navegador quedaron activados en este dispositivo.');
            return true;
        } catch (_) {
            informar('No fue posible activar los avisos del navegador. Puedes seguir consultándolos en el panel.');
            return false;
        }
    }

    async function recuperarSuscripcion() {
        if (!pushDisponible() || typeof win.navigator.serviceWorker.getRegistration !== 'function') return;
        try {
            const registro = await win.navigator.serviceWorker.getRegistration('/aprendiz/');
            if (!registro) return;
            suscripcion = await registro.pushManager.getSubscription();
            if (suscripcion && botonPush) botonPush.textContent = 'Desactivar avisos del navegador';
        } catch (_) {
            suscripcion = null;
            informar('No se pudo comprobar si este dispositivo tiene avisos activados. Los avisos del panel siguen funcionando.');
        }
    }

    async function retirarSuscripcion() {
        if (!suscripcion) return actualizarSuscripcion();
        try {
            const respuesta = await win.fetch(root.dataset.subscriptionUrl, {
                method: 'DELETE', credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': root.dataset.csrfToken },
                body: JSON.stringify({ endpoint: suscripcion.endpoint }),
            });
            if (!respuesta.ok) throw new Error('No se pudo retirar la suscripción.');
            await suscripcion.unsubscribe();
            suscripcion = null;
            if (botonPush) botonPush.textContent = 'Activar avisos del navegador';
            informar('Los avisos del navegador quedaron desactivados en este dispositivo.');
            return true;
        } catch (_) {
            informar('No fue posible desactivar los avisos. Inténtalo de nuevo.');
            return false;
        }
    }

    function iniciar() {
        if (botonSonido) botonSonido.addEventListener('click', () => activarSonido());
        if (botonPush) botonPush.addEventListener('click', () => {
            return suscripcion ? retirarSuscripcion() : actualizarSuscripcion();
        });
        if (win.MutationObserver && experiencia) {
            const observador = new win.MutationObserver(() => {
                if (modoSilencioso()) informar('«Lectura tranquila» conserva el texto y silencia el sonido.');
            });
            observador.observe(experiencia, { attributes: true, attributeFilter: ['data-experience-notification-mode'] });
        }
        const inicio = (async () => {
            await recuperarSuscripcion();
            await consultarNuevas();
        })();
        const temporizador = win.setInterval(() => consultarNuevas(), 15000);
        return { inicio, consultarNuevas, activarSonido, actualizarSuscripcion, retirarSuscripcion, modoSilencioso, detener: () => win.clearInterval(temporizador) };
    }

    return iniciar();
}

function iniciarNotificacionesAprendiz(doc = document, win = window) {
    const root = doc.querySelector('[data-aprendiz-notifications]');
    return root ? crearControlNotificacionesAprendiz(root, win, doc) : null;
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = { claveServidorPush, crearControlNotificacionesAprendiz, iniciarNotificacionesAprendiz };
}

if (typeof window !== 'undefined' && typeof document !== 'undefined') {
    document.addEventListener('DOMContentLoaded', () => { iniciarNotificacionesAprendiz(document, window); }, { once: true });
}
