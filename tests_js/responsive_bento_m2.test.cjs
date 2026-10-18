const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const stylesPath = path.join(__dirname, '..', 'app', 'static', 'css', 'styles.css');
const planEvalPath = path.join(__dirname, '..', 'app', 'static', 'css', 'planeacion_evaluaciones.css');
const alertasPath = path.join(__dirname, '..', 'app', 'templates', 'instructor', 'alertas.html');
const observadorPath = path.join(__dirname, '..', 'app', 'templates', 'instructor', 'observador.html');
const juiciosPath = path.join(__dirname, '..', 'app', 'templates', 'instructor', 'juicios.html');

const stylesCss = fs.readFileSync(stylesPath, 'utf8');
const planEvalCss = fs.readFileSync(planEvalPath, 'utf8');
const alertasHtml = fs.readFileSync(alertasPath, 'utf8');
const observadorHtml = fs.readFileSync(observadorPath, 'utf8');
const juiciosHtml = fs.readFileSync(juiciosPath, 'utf8');

test('F07: adaptación y contención de cabecera en .nav-shell para viewports móviles (<= 420px y <= 360px)', () => {
    // En pantallas de 420px o menos, nav-shell debe permitir flex-wrap y limitar su caja
    assert.match(stylesCss, /@media\s*\(max-width:\s*420px\)\s*\{[\s\S]*?\.nav-shell\s*\{[\s\S]*?flex-wrap:\s*wrap;/);
    assert.match(stylesCss, /@media\s*\(max-width:\s*420px\)\s*\{[\s\S]*?\.nav-shell\s*\{[\s\S]*?box-sizing:\s*border-box;/);

    // En pantallas ultraestrechas (<= 360px), se garantiza contención del brand y ellipsis en el título
    assert.match(stylesCss, /@media\s*\(max-width:\s*360px\)\s*\{[\s\S]*?\.nav-shell\s*\{[\s\S]*?flex-wrap:\s*wrap;/);
    assert.match(stylesCss, /@media\s*\(max-width:\s*360px\)\s*\{[\s\S]*?\.nav-brand\s*\{[\s\S]*?max-width:\s*calc/);
});

test('F06: encapsulación accesible en .table-responsive de tablas del panel de instructores', () => {
    // 1. Alertas: la tabla de reglas de resolución está envuelta en table-responsive accesible
    assert.match(alertasHtml, /<div\s+class="table-responsive"\s+tabindex="0"\s+role="region"\s+aria-label="Tabla de reglas automáticas de resolución">[\s\S]*?<table/);

    // 2. Observador: la tabla de resumen por aprendiz cuenta con contenedor accesible
    assert.match(observadorHtml, /<div\s+class="table-responsive"\s+tabindex="0"\s+role="region"\s+aria-label="Tabla de resumen por aprendiz">[\s\S]*?<table\s+class="resumen-tabla">/);

    // 3. Juicios: la tabla de avance global cuenta con región etiquetada y navegable por teclado
    assert.match(juiciosHtml, /<div\s+class="table-responsive"\s+tabindex="0"\s+role="region"\s+aria-label="Tabla de avance global por aprendiz">[\s\S]*?<table\s+class="table/);
});

test('F08: estandarización de tarjetas Bento con radio uniforme y superficies sólidas', () => {
    // La regla base de .card unifica radio y bordes sutiles
    assert.match(stylesCss, /\.card\s*\{[\s\S]*?border-radius:\s*var\(--radius\);/);
    assert.match(stylesCss, /\.card\s*\{[\s\S]*?padding:\s*clamp\(16px,\s*4vw,\s*24px\);/);

    // Tema Sena provee superficies Bento sólidas y legibles
    assert.match(stylesCss, /\[data-theme="sena"\][\s\S]*?--bg-glass:\s*rgba\(255,\s*255,\s*255,\s*0\.94\);/);
});

test('F09: reorganización de cuadrículas densas en pantallas móviles ultraestrechas', () => {
    // .vision-recommendations-grid utiliza límite inferior fluido min(100%, 280px)
    assert.match(stylesCss, /\.vision-recommendations-grid\s*\{[\s\S]*?grid-template-columns:\s*repeat\(auto-fit,\s*minmax\(min\(100%,\s*280px\),\s*1fr\)\);/);

    // .followup-settings-grid se adapta a 1 columna en <= 420px
    assert.match(stylesCss, /@media\s*\(max-width:\s*420px\)\s*\{[\s\S]*?\.followup-settings-grid[\s\S]*?grid-template-columns:\s*1fr;/);

    // .pl-eval-metricas se adapta a 1 columna en pantallas ultraestrechas (<= 420px)
    assert.match(planEvalCss, /@media\s*\(max-width:\s*420px\)\s*\{[\s\S]*?\.pl-eval-metricas\s*\{[\s\S]*?grid-template-columns:\s*1fr;/);
});
