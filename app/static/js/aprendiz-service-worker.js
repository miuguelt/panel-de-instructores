'use strict';

function registrarServiceWorker(self) {
    self.addEventListener('push', event => {
        event.waitUntil((async () => {
            const ventanas = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
            if (ventanas.some(cliente => cliente.visibilityState === 'visible')) return;
            let datos = {};
            try { datos = event.data ? event.data.json() : {}; } catch (_) { datos = {}; }
            const ruta = typeof datos.url === 'string' && /^\/aprendiz\/\d+\/notificaciones$/.test(datos.url)
                ? datos.url : '/aprendiz/';
            await self.registration.showNotification('Resultados formativos actualizados', {
                body: 'Entra al panel para consultar la información.',
                icon: '/static/img/logo.png',
                badge: '/static/img/logo.png',
                tag: 'actualizacion-formativa',
                renotify: false,
                silent: Boolean(datos.silent),
                data: { ruta },
            });
        })());
    });

    self.addEventListener('notificationclick', event => {
        event.notification.close();
        event.waitUntil((async () => {
            const ruta = event.notification.data?.ruta;
            const destino = typeof ruta === 'string' && /^\/aprendiz\/\d+\/notificaciones$/.test(ruta)
                ? new URL(ruta, self.location.origin).href : new URL('/aprendiz/', self.location.origin).href;
            const clientes = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
            const existente = clientes.find(cliente => {
                const url = new URL(cliente.url);
                return url.origin === self.location.origin && url.pathname.startsWith('/aprendiz/');
            });
            if (existente) {
                await existente.navigate(destino);
                await existente.focus();
            } else {
                await self.clients.openWindow(destino);
            }
        })());
    });
}

if (typeof module !== 'undefined' && module.exports) module.exports = registrarServiceWorker;
if (typeof self !== 'undefined') registrarServiceWorker(self);
