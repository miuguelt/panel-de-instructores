const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const asistenciaPath = path.join(__dirname, '..', 'app', 'templates', 'instructor', 'asistencia.html');
const rankingPath = path.join(__dirname, '..', 'app', 'templates', 'instructor', 'ranking.html');
const basePath = path.join(__dirname, '..', 'app', 'templates', 'base.html');
const modalCssPath = path.join(__dirname, '..', 'app', 'static', 'css', 'modal-system.css');

const asistenciaHtml = fs.readFileSync(asistenciaPath, 'utf8');
const rankingHtml = fs.readFileSync(rankingPath, 'utf8');
const baseHtml = fs.readFileSync(basePath, 'utf8');
const modalCss = fs.readFileSync(modalCssPath, 'utf8');

test('F11: disparador HTMX de novedades en asistencia es un botón accesible por teclado', () => {
    // Debe ser un <button type="button"> accesible con aria-label descriptivo y no un <span> mudo
    assert.match(asistenciaHtml, /<button\s+type="button"\s+class="aprendiz-name"\s+id="aprendiz-{{ ap\.id }}"[\s\S]*?aria-label="Ver detalles y novedades de/);
    assert.doesNotMatch(asistenciaHtml, /<span\s+class="aprendiz-name"/);
});

test('F12: la región de sondeo dinámico de ranking anuncia actualizaciones con aria-live', () => {
    // La sección #ranking-lista debe contar con rol de región, aria-live="polite" y aria-atomic="true"
    assert.match(rankingHtml, /<section\s+id="ranking-lista"[\s\S]*?role="region"[\s\S]*?aria-live="polite"[\s\S]*?aria-atomic="true"/);
});

test('F10: sistema de modales garantiza controles táctiles de 44px preservando cota base de 42px', () => {
    // modal-system.css debe cubrir botones, enlaces, selects e inputs con 44px
    assert.match(modalCss, /\.app-modal-content\s+button,[\s\S]*?\.app-modal-content\s+a,[\s\S]*?\.app-modal-content\s+select/);
    assert.match(modalCss, /min-height:\s*44px;/);
    assert.match(modalCss, /min-width:\s*44px;/);
    // Conserva min-height: 42px para aserción estricta de modal_system.test.cjs
    assert.match(modalCss, /min-height:\s*42px;/);
});

test('F13: botones interactivos huérfanos disponen de nombres accesibles (aria-label)', () => {
    // Botón flotante de cambio de tema
    assert.match(baseHtml, /class="theme-float-single-btn"[\s\S]*?aria-label="Cambiar tema de interfaz"/);
    // Botón de notificaciones en navbar
    assert.match(baseHtml, /class="nav-icon-button"[\s\S]*?aria-label="Notificaciones/);
});
