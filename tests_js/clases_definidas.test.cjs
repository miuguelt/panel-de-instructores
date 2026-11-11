/**
 * Contrato de clases definidas (10 de noviembre de 2026).
 *
 * La aplicación no carga Bootstrap, pero varias plantillas usan nombres con su
 * convención (`d-flex`, `mb-3`, `text-success`, `table-hover`…). Sin una regla
 * propia, esas zonas pierden su composición: cabeceras apiladas, barras de
 * progreso invisibles y tablas sin separación. Estas pruebas vigilan que:
 *   1. Toda clase utilitaria usada en una plantilla tenga regla en `app/static/css`.
 *   2. Los componentes estructurales que antes no tenían estilo lo conserven.
 *   3. `utilidades.css` se cargue después de `styles.css` y antes de las hojas de página.
 *   4. El número de clases sin regla ni gancho de JavaScript solo pueda bajar.
 *
 * Se ejecuta con `node --test tests_js/clases_definidas.test.cjs`.
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const raiz = path.resolve(__dirname, '..');
const cssDir = path.join(raiz, 'app', 'static', 'css');
const jsDir = path.join(raiz, 'app', 'static', 'js');
const plantillasDir = path.join(raiz, 'app', 'templates');

function listarArchivos(dir, extension) {
    const encontrados = [];
    for (const entrada of fs.readdirSync(dir, { withFileTypes: true })) {
        const ruta = path.join(dir, entrada.name);
        if (entrada.isDirectory()) encontrados.push(...listarArchivos(ruta, extension));
        else if (entrada.name.endsWith(extension)) encontrados.push(ruta);
    }
    return encontrados;
}

const leer = archivo => fs.readFileSync(archivo, 'utf8');
const etiqueta = archivo => path.relative(raiz, archivo).replace(/\\/g, '/');

function clasesDefinidas() {
    const css = listarArchivos(cssDir, '.css').map(leer).join('\n').replace(/\/\*[\s\S]*?\*\//g, '');
    return new Set([...css.matchAll(/\.(-?[_a-zA-Z][\w-]*)/g)].map(m => m[1]));
}

function codigoJavaScript(plantillas) {
    const externo = listarArchivos(jsDir, '.js').map(leer);
    const enLinea = plantillas.flatMap(({ texto }) => [...texto.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)].map(m => m[1]));
    return [...externo, ...enLinea].join('\n');
}

/** Clases estáticas de cada plantilla; descarta segmentos Jinja y prefijos dinámicos. */
function clasesEnPlantillas() {
    const plantillas = listarArchivos(plantillasDir, '.html').map(archivo => ({ archivo, texto: leer(archivo) }));
    const usos = new Map();
    for (const { archivo, texto } of plantillas) {
        for (const match of texto.matchAll(/class="([^"]*)"/g)) {
            const estatico = match[1].replace(/\{[%{][\s\S]*?[%}]\}/g, ' ');
            for (const clase of estatico.split(/\s+/)) {
                if (!/^[a-zA-Z][\w-]*[a-zA-Z0-9]$/.test(clase)) continue;
                if (!usos.has(clase)) usos.set(clase, new Set());
                usos.get(clase).add(etiqueta(archivo));
            }
        }
    }
    return { usos, plantillas };
}

const UTILITARIA = /^(d|m[tbsexy]?|p[tbsexy]?|gap|align|justify|flex|row|col|container|text|bg|border|shadow|font|small|h[1-6]|table|progress|spinner|form-(control|select)-sm|form-label|btn-close)(-|$)/;

test('toda clase utilitaria usada en plantillas tiene regla propia', () => {
    const definidas = clasesDefinidas();
    const { usos } = clasesEnPlantillas();
    const faltantes = [...usos.entries()]
        .filter(([clase]) => UTILITARIA.test(clase) && !definidas.has(clase))
        .map(([clase, archivos]) => `${clase} (${[...archivos].join(', ')})`);
    assert.deepEqual(faltantes, [], `Clases utilitarias sin regla:\n${faltantes.join('\n')}`);
});

const ESTRUCTURALES = [
    'empty-icon',
    'reglamento-card',
    'fila-sustento',
    'devbrain-prose',
    'fundamento-normativo',
    'fundamento-lista',
    'fundamento-item',
    'app-modal-title',
    'app-modal-content--large',
    'raps-vencidos-modal-shell',
    'raps-vencidos-header-wrap',
    'raps-vencidos-toolbar',
    'raps-vencidos-list',
    'report-portafolio-grid',
    'report-portafolio-card',
    'report-competency-section',
    'portafolio-item-box',
    'urgent-card-body',
    'urgent-card-footer',
    'urgent-card-status',
    'vision-card-body',
    'bento-kpi-footer',
    'badge-primary',
    'badge-accent',
    'badge-ghost',
    'badge-sm',
    'badge-subtle',
    'alert-content',
    'card-subtle',
    'hover-link',
];

test('los componentes estructurales de las plantillas tienen regla', () => {
    const definidas = clasesDefinidas();
    const faltantes = ESTRUCTURALES.filter(clase => !definidas.has(clase));
    assert.deepEqual(faltantes, [], `Componentes sin regla: ${faltantes.join(', ')}`);
});

test('utilidades.css se carga después de styles.css y antes de las hojas de página', () => {
    const base = leer(path.join(plantillasDir, 'base.html'));
    const estilos = base.indexOf("filename='css/styles.css'");
    const utilidades = base.indexOf("filename='css/utilidades.css'");
    const pagina = base.indexOf('{% block page_css %}');
    assert.ok(estilos >= 0, 'base.html debe cargar styles.css');
    assert.ok(utilidades > estilos, 'utilidades.css debe cargarse después de styles.css');
    assert.ok(utilidades < pagina, 'utilidades.css debe cargarse antes del bloque page_css');
});

test('utilidades.css usa solo tokens del sistema, sin colores literales', () => {
    const css = leer(path.join(cssDir, 'utilidades.css')).replace(/\/\*[\s\S]*?\*\//g, '');
    const literales = css.match(/#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(/g) || [];
    assert.deepEqual(literales, [], 'utilidades.css no debe contener colores literales');
});

// Ratchet: clases sin regla CSS que tampoco usa ningún JavaScript (gancho). Solo puede bajar.
const PRESUPUESTO_SIN_REGLA = 145;

test('el número de clases sin regla ni gancho de JavaScript no crece', () => {
    const definidas = clasesDefinidas();
    const { usos, plantillas } = clasesEnPlantillas();
    const js = codigoJavaScript(plantillas);
    const sinRegla = [...usos.keys()].filter(clase =>
        !definidas.has(clase)
        && !clase.startsWith('js-')
        && !new RegExp(`['".\\s]${clase.replace(/[-]/g, '\\-')}\\b`).test(js));
    assert.ok(sinRegla.length <= PRESUPUESTO_SIN_REGLA,
        `Hay ${sinRegla.length} clases sin regla (presupuesto ${PRESUPUESTO_SIN_REGLA}):\n${sinRegla.sort().join(', ')}`);
});
