const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { chromium } = require('playwright');

const raiz = path.resolve(__dirname, '..');
const script = path.join(raiz, 'app/static/js/notificaciones_aprendiz.js');

test('el panel anuncia calificaciones nuevas, deduplica y respeta la activación de sonido', async () => {
    const navegador = await chromium.launch({ headless: true, channel: process.env.PANEL_TEST_BROWSER_CHANNEL || 'chromium' });
    try {
        const pagina = await navegador.newPage();
        await pagina.evaluate(() => {
            window.__respuestasAvisos = [];
            window.__consultasAvisos = [];
            window.__tonos = 0;
            window.fetch = async (url, opciones = {}) => {
                window.__consultasAvisos.push({ url, opciones });
                if (opciones.method === 'POST' || opciones.method === 'DELETE') return { ok: true };
                const datos = window.__respuestasAvisos.shift() || { notificaciones: [] };
                return { ok: true, async json() { return datos; } };
            };
            window.AudioContext = class {
                constructor() { this.destination = {}; this.currentTime = 0; }
                async resume() {}
                createOscillator() { return { frequency: {}, connect() {}, start() { window.__tonos += 1; }, stop() {} }; }
                createGain() { return { gain: {}, connect() {} }; }
            };
            window.setInterval = (callback, delay) => {
                window.__intervaloAvisos = { callback, delay };
                return 1;
            };
            window.clearInterval = () => {};
            Object.defineProperty(window.navigator, 'serviceWorker', {
                configurable: true,
                value: { async register() { return { pushManager: {
                    async getSubscription() { return null; },
                    async subscribe() { return { endpoint: 'https://updates.push.services.mozilla.com/push/v1/browser-test', toJSON() { return { endpoint: this.endpoint, keys: { p256dh: 'public', auth: 'auth' } }; }, async unsubscribe() { return true; } }; },
                } }; } },
            });
            Object.defineProperty(window, 'Notification', {
                configurable: true,
                value: { async requestPermission() { return 'granted'; } },
            });
            window.PushManager = function PushManager() {};
        });
        await pagina.setContent(`
            <main id="panel-aprendiz-root" data-experience-notification-mode="all">
                <section data-aprendiz-notifications
                    data-notification-cursor="0"
                    data-notification-poll-url="/aprendiz/9/notificaciones/nuevas"
                    data-subscription-url="/aprendiz/9/notificaciones/suscripcion"
                    data-service-worker-url="/aprendiz/service-worker.js"
                    data-vapid-public-key="AQID"
                    data-push-enabled="true"
                    data-csrf-token="csrf-browser">
                    <button type="button" data-enable-notification-sound>Activar sonido de avisos</button>
                    <button type="button" data-toggle-push>Activar avisos del navegador</button>
                    <p data-notification-status role="status" aria-live="polite"></p>
                    <div data-notification-live role="status" aria-live="polite" aria-atomic="false"></div>
                </section>
            </main>
        `);
        await pagina.addScriptTag({ path: script });
        await pagina.evaluate(async () => {
            window.__respuestasAvisos.push({ notificaciones: [
                { id: 1, tipo: 'calificacion', mensaje: 'Tu instructor publicó una calificación.', url: '/aprendiz/9/notificaciones' },
            ] });
            window.__controlAvisos = crearControlNotificacionesAprendiz(
                document.querySelector('[data-aprendiz-notifications]'), window, document,
            );
            await window.__controlAvisos.inicio;
        });
        assert.equal(await pagina.locator('[data-notification-live] [role="status"]').count(), 0);
        assert.equal(await pagina.locator('[data-notification-live]').getAttribute('aria-live'), 'polite');
        assert.match(await pagina.locator('[data-notification-live]').innerText(), /Tu instructor publicó una calificación/);
        assert.equal(await pagina.evaluate(() => window.__intervaloAvisos.delay), 15000);

        await pagina.getByRole('button', { name: 'Activar sonido de avisos' }).click();
        await pagina.evaluate(async () => {
            window.__respuestasAvisos.push({ notificaciones: [
                { id: 2, tipo: 'calificacion', mensaje: 'Se publicó un resultado nuevo.', url: '/aprendiz/9/notificaciones' },
            ] });
            await window.__intervaloAvisos.callback();
        });
        assert.equal(await pagina.evaluate(() => window.__tonos), 1);

        await pagina.evaluate(async () => {
            document.getElementById('panel-aprendiz-root').dataset.experienceNotificationMode = 'quiet';
            window.__respuestasAvisos.push({ notificaciones: [
                { id: 2, tipo: 'calificacion', mensaje: 'Aviso repetido.', url: '/aprendiz/9/notificaciones' },
                { id: 3, tipo: 'juicio_evaluativo', mensaje: 'Tu reporte de resultados fue actualizado.', url: '/aprendiz/9/notificaciones' },
            ] });
            await window.__intervaloAvisos.callback();
        });
        assert.equal(await pagina.locator('[data-notification-live] .learner-notification-toast').count(), 3);
        assert.equal(await pagina.evaluate(() => window.__tonos), 1);
        assert.match(await pagina.locator('[data-notification-status]').innerText(), /Lectura tranquila/);

        await pagina.getByRole('button', { name: 'Activar avisos del navegador' }).click();
        assert.match(await pagina.locator('[data-notification-status]').innerText(), /quedaron activados/);
        const datosPush = await pagina.evaluate(() => JSON.parse(window.__consultasAvisos.find(x => x.opciones.method === 'POST').opciones.body));
        assert.equal(datosPush.endpoint, 'https://updates.push.services.mozilla.com/push/v1/browser-test');
        assert.equal(await pagina.evaluate(() => window.__controlAvisos.modoSilencioso()), true);
        assert.deepEqual(await pagina.evaluate(() => window.__consultasAvisos.find(x => x.opciones.method === 'POST').opciones.headers['X-CSRFToken']), 'csrf-browser');
    } finally {
        await navegador.close();
    }
});
