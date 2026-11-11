/**
 * Contrato de composición responsive (10 de noviembre de 2026).
 *
 * La auditoría con datos extensos encontró que la información se desbordaba o
 * quedaba encima de otros elementos por cuatro patrones. Estas pruebas evitan
 * que vuelvan:
 *   1. Rejillas auto-fit/auto-fill con un mínimo fijo (minmax(280px, 1fr)) que no
 *      cabe en pantallas de 320 px.
 *   2. Una marca de ficha que no cede espacio y deja la navegación en 1 px.
 *   3. Cabeceras de página cuya columna de acciones reduce el título a 115 px.
 *   4. Columnas o nombres que se recortan con overflow: hidden en lugar de envolver.
 *
 * Se ejecuta con `node --test tests_js/composicion_responsive.test.cjs`.
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

const leer = archivo => fs.readFileSync(archivo, 'utf8');
const etiqueta = archivo => path.relative(raiz, archivo).replace(/\\/g, '/');
const sinComentarios = css => css.replace(/\/\*[\s\S]*?\*\//g, '');
const styles = sinComentarios(leer(path.join(cssDir, 'styles.css')));
const asistencia = sinComentarios(leer(path.join(cssDir, 'asistencia.css')));

/** Separa un texto CSS en reglas de primer nivel: { cabecera, cuerpo }. */
function reglasDePrimerNivel(css) {
    const reglas = [];
    let profundidad = 0;
    let inicioCabecera = 0;
    let inicioCuerpo = 0;
    for (let i = 0; i < css.length; i += 1) {
        if (css[i] === '{') {
            if (profundidad === 0) inicioCuerpo = i + 1;
            profundidad += 1;
        } else if (css[i] === '}') {
            profundidad -= 1;
            if (profundidad === 0) {
                reglas.push({ cabecera: css.slice(inicioCabecera, inicioCuerpo - 1).trim(), cuerpo: css.slice(inicioCuerpo, i) });
                inicioCabecera = i + 1;
            }
        }
    }
    return reglas;
}

/** Declaraciones de la última regla de primer nivel cuyo selector es exactamente `selector`. */
function ultimaRegla(css, selector) {
    const coincidencias = reglasDePrimerNivel(css).filter(r => r.cabecera === selector);
    assert.ok(coincidencias.length > 0, `Falta la regla ${selector}`);
    return coincidencias.at(-1).cuerpo;
}

/** Cuerpos de todos los bloques @media de primer nivel con la condición exacta. */
function bloquesMedia(css, condicion) {
    const bloques = reglasDePrimerNivel(css).filter(r => r.cabecera === `@media ${condicion}`).map(r => r.cuerpo);
    assert.ok(bloques.length > 0, `Falta @media ${condicion}`);
    return bloques;
}

/** Declaraciones de la última regla `selector` dentro de cualquier bloque @media con esa condición. */
function reglaEnMedia(css, condicion, selector) {
    const encontradas = bloquesMedia(css, condicion)
        .flatMap(cuerpo => reglasDePrimerNivel(cuerpo))
        .filter(r => r.cabecera.split(',').map(parte => parte.trim()).includes(selector));
    assert.ok(encontradas.length > 0, `Falta ${selector} dentro de @media ${condicion}`);
    return encontradas.at(-1).cuerpo;
}

test('ninguna rejilla auto-fit/auto-fill exige un mínimo fijo mayor que la pantalla', () => {
    const fijo = /repeat\((auto-fit|auto-fill),\s*minmax\(\s*[0-9.]+(px|rem)\s*,\s*1fr\s*\)\)/g;
    const hallazgos = [];
    for (const archivo of [...listarArchivos(cssDir, '.css'), ...listarArchivos(plantillasDir, '.html')]) {
        for (const m of leer(archivo).matchAll(fijo)) hallazgos.push(`${etiqueta(archivo)}: ${m[0]}`);
    }
    assert.deepEqual(hallazgos, [], `Usa minmax(min(100%, X), 1fr):\n${hallazgos.join('\n')}`);
});

test('la marca de la barra cede espacio y la navegación conserva el ancho de sus enlaces', () => {
    const marca = ultimaRegla(styles, '.nav-brand');
    assert.match(marca, /flex:\s*0 1 [^;]+;/, '.nav-brand debe poder encogerse');
    assert.match(marca, /min-width:\s*0/, '.nav-brand necesita min-width: 0 para encogerse');
    assert.match(ultimaRegla(styles, '.nav-primary'), /flex:\s*0 0 auto/, '.nav-primary no debe encogerse por debajo de sus enlaces');
    assert.match(ultimaRegla(styles, '.nav-shell'), /flex-wrap:\s*wrap/, '.nav-shell debe permitir una segunda fila');
});

test('por debajo de 1280 px la navegación baja a su propia fila con desplazamiento contenido', () => {
    const nav = reglaEnMedia(styles, '(max-width: 1279px)', '.nav-primary');
    assert.match(nav, /flex:\s*1 1 100%/);
    assert.match(nav, /overflow-x:\s*auto/);
    assert.match(nav, /min-width:\s*0/);
});

test('la columna de acciones de las cabeceras no reduce el título', () => {
    const columnas = reglaEnMedia(styles, '(min-width: 768px)', '.vision-header');
    assert.match(columnas, /grid-template-columns:\s*minmax\(min\(100%,\s*22rem\),\s*1fr\)\s*fit-content\(60%\)/);
});

test('las tarjetas de visión general caben en 390 px', () => {
    assert.match(ultimaRegla(styles, '.vision-two-col'), /minmax\(min\(100%,\s*380px\),\s*1fr\)/);
});

test('los campos de .form-row pasan de línea en lugar de comprimirse', () => {
    assert.match(ultimaRegla(styles, '.form-row > .form-group'), /flex:\s*1 1 min\(14rem,\s*100%\)/);
});

test('asistencia: el nombre del aprendiz envuelve y las estadísticas no se recortan', () => {
    const nombre = ultimaRegla(asistencia, '.aprendiz-name');
    assert.match(nombre, /white-space:\s*normal/);
    assert.doesNotMatch(nombre, /text-overflow:\s*ellipsis/);
    assert.doesNotMatch(ultimaRegla(asistencia, '.col-nombre'), /overflow:\s*hidden/);
    const estadisticas = reglaEnMedia(asistencia, '(max-width: 1100px)', '.asistencia-row .col-stats');
    assert.match(estadisticas, /grid-column:\s*1 \/ -1/);
    assert.match(estadisticas, /overflow:\s*visible/);
});

test('menú de la ficha: el panel «Más módulos» solo se muestra abierto', () => {
    // Un display propio en la regla base anularía el ocultamiento nativo del popover.
    assert.doesNotMatch(ultimaRegla(styles, '.ficha-nav-popover'), /display\s*:/);
    assert.match(ultimaRegla(styles, '.ficha-nav-popover:popover-open'), /display:\s*grid/);
    assert.match(ultimaRegla(styles, '.ficha-nav-popover:popover-open'), /minmax\(min\(100%,\s*14rem\),\s*1fr\)/);
});

test('menú de la ficha: el botón «Más módulos» queda visible al desplazar y se ancla al panel', () => {
    const boton = ultimaRegla(styles, '.ficha-nav-more');
    assert.match(boton, /position:\s*sticky/);
    assert.match(boton, /right:\s*0/);
    assert.match(boton, /min-height:\s*44px|min-height:\s*42px/);
    assert.match(styles, /@supports \(anchor-name: --ficha-nav-mas\)\s*\{[\s\S]*?position-anchor:\s*--ficha-nav-mas/);
});

test('menú de la ficha: en celular el texto genérico se oculta solo visualmente', () => {
    const oculto = reglaEnMedia(styles, '(max-width: 760px)', '.ficha-nav-more:not(.is-active) .ficha-nav-more-text');
    assert.match(oculto, /clip-path:\s*inset\(50%\)/);
    assert.doesNotMatch(oculto, /display:\s*none/);
});
