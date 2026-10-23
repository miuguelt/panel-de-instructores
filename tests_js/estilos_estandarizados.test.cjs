/**
 * Contrato estático del sistema visual unificado (23 de octubre de 2026).
 *
 * Estas pruebas vigilan que las plantillas y los CSS consuman solo tokens y
 * clases canónicas definidas en `app/static/css/styles.css`:
 *   1. Toda variable `var(--x)` existe o es un token dinámico inyectado por JS/Jinja.
 *   2. Todo modificador de variante `.btn-*` usado en plantillas está definido.
 *   3. Ninguna plantilla declara bloques `<style>` propios (salvo el `noscript` de base.html).
 *   4. Ningún `style="..."` estático contiene colores literales fuera de un
 *      fallback `var(--token, #hex)`; Jinja y las plantillas JS son dinámicas.
 *   5. Ningún icono `<i>`/`<svg>` fija ancho y alto en píxeles a la vez.
 *   6. El presupuesto de atributos `style=` es un ratchet que solo puede bajar.
 *
 * Se ejecuta con `node tests_js/estilos_estandarizados.test.cjs`.
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const raiz = path.resolve(__dirname, '..');
const cssDir = path.join(raiz, 'app', 'static', 'css');
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

const archivosCss = () => listarArchivos(cssDir, '.css');
const archivosPlantilla = () => listarArchivos(plantillasDir, '.html');
const leer = archivo => fs.readFileSync(archivo, 'utf8');
const etiqueta = archivo => path.relative(raiz, archivo).replace(/\\/g, '/');

// Tokens que no viven en CSS: los calcula JS en tiempo de ejecución o los inyecta
// una plantilla con Jinja. Es una lista explícita, no un comodín.
const TOKENS_DINAMICOS = new Set([
    '--progress-value',
    '--metric-value',
    '--metric-color',
    '--state-color',
    '--btn-color',
    '--marker-position',
    '--experience-percent',
    '--deadline-progress',
    '--summary-value',
    '--tyt-value',
    '--pl-cols',
    '--pl-hoy',
    '--pl-avance',
    '--learner-custom-accent',
    '--learner-custom-accent-soft',
    '--learner-accent-foreground',
    '--ga',
    '--ga-bg',
    '--ga-text',
    '--ga-border',
]);

// Presupuesto máximo de atributos style= en plantillas. Es un ratchet: solo
// puede bajar. Tras la migración de los frentes de plantillas (instructor y
// aprendiz/grupos) el total real quedó en 695, así que se fija en 720 para dar
// un margen pequeño sin permitir que vuelva a crecer.
const MAX_ATRIBUTOS_STYLE = 720;

const PREFIJOS_VARIANTE_BTN = /^btn-(primary|secondary|outline|ghost|link|danger|success|warning|info|icon|sm|xs|lg|full|group)/;

// Hooks de comportamiento que comparten prefijo con una familia de variantes
// pero no son variantes visuales (no necesitan regla propia en CSS).
const HOOKS_BTN_PERMITIDOS = new Set(['btn-group-edit']);

const COLOR_LITERAL = /#[0-9a-fA-F]{3,8}\b|\brgba?\s*\(|\bhsla?\s*\(/;

// Devuelve el valor sin las llamadas var(...) completas: los fallbacks dentro
// de un token (var(--x, #hex)) son legítimos y no cuentan como color literal.
function sinTokensVar(valor) {
    let resultado = '';
    let cursor = 0;
    while (cursor < valor.length) {
        const inicio = valor.indexOf('var(', cursor);
        if (inicio === -1) {
            resultado += valor.slice(cursor);
            break;
        }
        resultado += valor.slice(cursor, inicio);
        let profundidad = 0;
        let fin = inicio + 3; // apunta al paréntesis de apertura
        for (; fin < valor.length; fin += 1) {
            if (valor[fin] === '(') profundidad += 1;
            else if (valor[fin] === ')') {
                profundidad -= 1;
                if (profundidad === 0) { fin += 1; break; }
            }
        }
        cursor = fin;
    }
    return resultado;
}

function atributosStyle(texto) {
    const valores = [];
    for (const coincidencia of texto.matchAll(/style\s*=\s*("([^"]*)"|'([^']*)')/g)) {
        valores.push(coincidencia[2] !== undefined ? coincidencia[2] : coincidencia[3]);
    }
    return valores;
}

function clasesDeclaradas(texto) {
    const clases = [];
    for (const coincidencia of texto.matchAll(/class\s*=\s*("([^"]*)"|'([^']*)')/g)) {
        const valor = coincidencia[2] !== undefined ? coincidencia[2] : coincidencia[3];
        clases.push(...valor.split(/\s+/).filter(Boolean));
    }
    return clases;
}

function esEstatico(valor) {
    // Jinja ({{ }} / {% %}) y plantillas JS (`${...}`) son valores dinámicos.
    return !valor.includes('{{') && !valor.includes('{%') && !valor.includes('${');
}

test('toda variable var(--x) usada en CSS o plantillas está definida o es un token dinámico', () => {
    const definidas = new Set();
    for (const archivo of archivosCss()) {
        for (const coincidencia of leer(archivo).matchAll(/(--[a-zA-Z0-9_-]+)\s*:/g)) {
            definidas.add(coincidencia[1]);
        }
    }
    assert.ok(definidas.has('--surface-glass'), 'styles.css debe declarar los tokens del sistema');

    const faltantes = new Map();
    const revisar = (archivo) => {
        for (const coincidencia of leer(archivo).matchAll(/var\(\s*(--[a-zA-Z0-9_-]+)/g)) {
            const nombre = coincidencia[1];
            if (definidas.has(nombre) || TOKENS_DINAMICOS.has(nombre)) continue;
            if (!faltantes.has(nombre)) faltantes.set(nombre, new Set());
            faltantes.get(nombre).add(etiqueta(archivo));
        }
    };
    for (const archivo of archivosCss()) revisar(archivo);
    for (const archivo of archivosPlantilla()) revisar(archivo);

    const detalle = [...faltantes.entries()]
        .map(([nombre, archivos]) => `${nombre} (${[...archivos].sort().join(', ')})`)
        .sort();
    assert.deepEqual(
        detalle,
        [],
        'Variables usadas sin definir en CSS y ausentes de la lista de tokens dinámicos:\n  ' + detalle.join('\n  ')
    );
});

test('todo modificador de variante btn-* usado en plantillas está definido en CSS', () => {
    const definidas = new Set();
    for (const archivo of archivosCss()) {
        for (const coincidencia of leer(archivo).matchAll(/\.(btn-[a-zA-Z0-9_-]+)/g)) {
            definidas.add(coincidencia[1]);
        }
    }

    const usadas = new Map();
    for (const archivo of archivosPlantilla()) {
        for (const clase of clasesDeclaradas(leer(archivo))) {
            if (!/^btn-[a-zA-Z0-9_-]+$/.test(clase)) continue;
            if (HOOKS_BTN_PERMITIDOS.has(clase)) continue; // hook de comportamiento
            if (!PREFIJOS_VARIANTE_BTN.test(clase)) continue; // hook de comportamiento, no variante
            if (!usadas.has(clase)) usadas.set(clase, new Set());
            usadas.get(clase).add(etiqueta(archivo));
        }
    }

    const sinDefinir = [...usadas.entries()]
        .filter(([clase]) => !definidas.has(clase))
        .map(([clase, archivos]) => `${clase} (${[...archivos].sort().join(', ')})`)
        .sort();
    assert.deepEqual(
        sinDefinir,
        [],
        'Variantes de botón usadas en plantillas sin regla en CSS:\n  ' + sinDefinir.join('\n  ')
    );
});

test('las plantillas no declaran bloques <style> propios (solo se admite el noscript de base.html)', () => {
    const baseHtml = path.join(plantillasDir, 'base.html');
    const sobrantes = [];

    // El único bloque permitido: el <style> dentro de <noscript> de base.html.
    const base = leer(baseHtml);
    assert.match(
        base,
        /<noscript>\s*<style>[\s\S]*?<\/style>\s*<\/noscript>/i,
        'base.html debe conservar el <style> de <noscript> que evita el overlay de carga sin JavaScript'
    );

    for (const archivo of archivosPlantilla()) {
        let texto = leer(archivo);
        if (archivo === baseHtml) {
            texto = texto.replace(/<noscript>\s*<style>[\s\S]*?<\/style>\s*<\/noscript>/gi, '');
        }
        const bloques = [...texto.matchAll(/<style\b/gi)];
        if (bloques.length) sobrantes.push(`${etiqueta(archivo)} (${bloques.length})`);
    }

    assert.deepEqual(
        sobrantes,
        [],
        'Plantillas con CSS incrustado: ' + (sobrantes.join(', ') || 'ninguna') +
        '. Debe moverse a app/static/css/*.css y enlazarse con {% block page_css %}.'
    );
});

test('ningún atributo style= estático contiene colores literales fuera de un token', () => {
    const hallazgos = [];
    for (const archivo of archivosPlantilla()) {
        for (const valor of atributosStyle(leer(archivo))) {
            if (!esEstatico(valor)) continue;
            // Los fallbacks de var(--token, #hex) son legítimos: solo se
            // consideran literales los colores sin token que los respalde.
            if (COLOR_LITERAL.test(sinTokensVar(valor))) {
                hallazgos.push(`${etiqueta(archivo)} :: ${valor.trim().slice(0, 90)}`);
            }
        }
    }
    assert.deepEqual(
        hallazgos,
        [],
        'Colores literales dentro de style= (usa tokens del sistema):\n  ' + hallazgos.join('\n  ')
    );
});

test('ningún icono (i/svg) fija ancho y alto estáticos en píxeles dentro de style=', () => {
    const hallazgos = [];
    for (const archivo of archivosPlantilla()) {
        const texto = leer(archivo);
        for (const coincidencia of texto.matchAll(/<([a-zA-Z][a-zA-Z0-9-]*)\b[^>]*?style\s*=\s*("([^"]*)"|'([^']*)')/g)) {
            const etiquetaHtml = coincidencia[1].toLowerCase();
            if (etiquetaHtml !== 'i' && etiquetaHtml !== 'svg') continue;
            const valor = coincidencia[3] !== undefined ? coincidencia[3] : coincidencia[4];
            if (!esEstatico(valor)) continue;
            const ancho = /\bwidth\s*:\s*\d+px\b/.test(valor);
            const alto = /\bheight\s*:\s*\d+px\b/.test(valor);
            if (ancho && alto) {
                hallazgos.push(`${etiqueta(archivo)} <${coincidencia[1]}> :: ${valor.trim().slice(0, 90)}`);
            }
        }
    }
    assert.deepEqual(
        hallazgos,
        [],
        'Iconos con ancho/alto en línea (usa .icon-sm, .icon-md, .icon-lg o .icon-inline):\n  ' + hallazgos.join('\n  ')
    );
});

test('el total de atributos style= en plantillas no supera el presupuesto del ratchet', () => {
    let total = 0;
    const porPlantilla = [];
    for (const archivo of archivosPlantilla()) {
        const cuenta = (leer(archivo).match(/\sstyle\s*=/g) || []).length;
        total += cuenta;
        if (cuenta) porPlantilla.push([cuenta, etiqueta(archivo)]);
    }
    porPlantilla.sort((a, b) => b[0] - a[0]);

    assert.ok(
        total <= MAX_ATRIBUTOS_STYLE,
        `Hay ${total} atributos style= y el máximo del contrato es ${MAX_ATRIBUTOS_STYLE}. ` +
        'Top: ' + porPlantilla.slice(0, 8).map(([n, f]) => `${f} (${n})`).join(', ')
    );
});

test('los generadores JS declaran las clases canónicas y no inyectan estilos con colores', () => {
    const generadores = [
        'app/static/js/table-filters.js',
        'app/static/js/uploads.js',
        'app/static/js/uploads_reanudables.js',
    ];
    for (const relativo of generadores) {
        const texto = leer(path.join(raiz, relativo));
        assert.doesNotMatch(texto, /style\.cssText/, `${relativo} no debe usar style.cssText`);
    }

    const filtros = leer(path.join(raiz, 'app/static/js/table-filters.js'));
    assert.doesNotMatch(filtros, /🔍/, 'table-filters.js no debe volver al emoji de lupa');
    assert.match(filtros, /table-toolbar/, 'table-filters.js debe usar .table-toolbar');
    assert.match(filtros, /table-filters-container/, 'table-filters.js debe usar .table-filters-container');
    assert.match(filtros, /table-filter-search/, 'table-filters.js debe usar .table-filter-search');
    assert.match(filtros, /table-filter-select/, 'table-filters.js debe usar .table-filter-select');
    assert.match(filtros, /table-filter-result/, 'table-filters.js debe usar .table-filter-result');
    assert.match(filtros, /table-filter-empty/, 'table-filters.js debe usar .table-filter-empty');
    assert.match(filtros, /table-filter-toggle/, 'table-filters.js debe usar .table-filter-toggle');
    assert.match(filtros, /btn btn-sm btn-outline/, 'el botón generado debe conservar los 42 px de .btn-sm');
    assert.match(filtros, /data-lucide="search"/, 'table-filters.js debe usar el icono Lucide de búsqueda');

    const uploads = leer(path.join(raiz, 'app/static/js/uploads.js'));
    for (const clase of ['upload-progress', 'upload-progress-text', 'upload-progress-bar', 'upload-progress-fill', 'upload-error']) {
        assert.match(uploads, new RegExp(clase), `uploads.js debe usar .${clase}`);
    }
    const reanudables = leer(path.join(raiz, 'app/static/js/uploads_reanudables.js'));
    assert.match(reanudables, /upload-progress-fill/, 'uploads_reanudables.js debe reutilizar .upload-progress-fill');
});
