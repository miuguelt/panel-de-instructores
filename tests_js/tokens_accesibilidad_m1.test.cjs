const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const stylesPath = path.join(__dirname, '..', 'app', 'static', 'css', 'styles.css');
const modalStylesPath = path.join(__dirname, '..', 'app', 'static', 'css', 'modal-system.css');

const stylesCss = fs.readFileSync(stylesPath, 'utf8');
const modalCss = fs.readFileSync(modalStylesPath, 'utf8');

// Función estándar W3C para luminancia relativa y ratio de contraste
function srgbToLinear(c) {
    const v = c / 255;
    return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
}

function hexToRgb(hex) {
    const clean = hex.replace('#', '').trim();
    if (clean.length === 3) {
        return {
            r: parseInt(clean[0] + clean[0], 16),
            g: parseInt(clean[1] + clean[1], 16),
            b: parseInt(clean[2] + clean[2], 16)
        };
    }
    return {
        r: parseInt(clean.substring(0, 2), 16),
        g: parseInt(clean.substring(2, 4), 16),
        b: parseInt(clean.substring(4, 6), 16)
    };
}

function getLuminance(hex) {
    const { r, g, b } = hexToRgb(hex);
    return 0.2126 * srgbToLinear(r) + 0.7152 * srgbToLinear(g) + 0.0722 * srgbToLinear(b);
}

function getContrastRatio(hex1, hex2) {
    const lum1 = getLuminance(hex1);
    const lum2 = getLuminance(hex2);
    const lighter = Math.max(lum1, lum2);
    const darker = Math.min(lum1, lum2);
    return (lighter + 0.05) / (darker + 0.05);
}

test('tokens semánticos institucionales estandarizados en :root', () => {
    assert.match(stylesCss, /--status-success-text:\s*#166534/);
    assert.match(stylesCss, /--status-success-bg:\s*rgba\(22,\s*101,\s*52,\s*0\.12\)/);
    assert.match(stylesCss, /--status-info-text:\s*#1d4ed8/);
    assert.match(stylesCss, /--status-info-bg:\s*rgba\(29,\s*78,\s*216,\s*0\.12\)/);
    assert.match(stylesCss, /--status-warning-text:\s*#7c2d12/);
    assert.match(stylesCss, /--status-warning-bg:\s*rgba\(245,\s*158,\s*11,\s*0\.14\)/);
    assert.match(stylesCss, /--status-danger-text:\s*#991b1b/);
    assert.match(stylesCss, /--status-danger-bg:\s*rgba\(239,\s*68,\s*68,\s*0\.12\)/);
});

test('tokens semánticos accesibles definidos en los tres temas de la aplicación', () => {
    // Tema 1: Elegant
    assert.match(stylesCss, /\[data-theme="elegant"\][\s\S]*?--status-success-text:\s*#166534/);
    assert.match(stylesCss, /\[data-theme="elegant"\][\s\S]*?--status-info-text:\s*#1d4ed8/);

    // Tema 2: Sena
    assert.match(stylesCss, /\[data-theme="sena"\][\s\S]*?--status-success-text:\s*#1e5900/);
    assert.match(stylesCss, /\[data-theme="sena"\][\s\S]*?--status-info-text:\s*#1d4ed8/);
    assert.match(stylesCss, /\[data-theme="sena"\][\s\S]*?--text-muted:\s*#466146/);

    // Tema 3: Ocean / Dark
    assert.match(stylesCss, /\[data-theme="ocean"\][\s\S]*?--status-success-text:\s*#4ade80/);
    assert.match(stylesCss, /\[data-theme="ocean"\][\s\S]*?--status-info-text:\s*#38bdf8/);
    assert.match(stylesCss, /\[data-theme="ocean"\][\s\S]*?--status-warning-text:\s*#fbbf24/);
    assert.match(stylesCss, /\[data-theme="ocean"\][\s\S]*?--status-danger-text:\s*#f87171/);
});

test('subsanación de contrastes WCAG AA (>= 4.5:1 para texto normal)', () => {
    // 1. Texto verde sobre fondo blanco en tema elegante/claro
    const contrastVerdeClaro = getContrastRatio('#166534', '#ffffff');
    assert.ok(contrastVerdeClaro >= 4.5, `Ratio verde claro: ${contrastVerdeClaro} debe ser >= 4.5`);

    // 2. Texto verde sobre fondo de tema sena (#f0f7ec)
    const contrastVerdeSena = getContrastRatio('#1e5900', '#f0f7ec');
    assert.ok(contrastVerdeSena >= 4.5, `Ratio verde sena: ${contrastVerdeSena} debe ser >= 4.5`);

    // 3. Texto azul de información (#1d4ed8) sobre blanco
    const contrastAzulClaro = getContrastRatio('#1d4ed8', '#ffffff');
    assert.ok(contrastAzulClaro >= 4.5, `Ratio azul info: ${contrastAzulClaro} debe ser >= 4.5`);

    // 4. Texto oscuro (#0f172a) sobre botón warning (#ff6a00 y #d97706)
    const contrastBtnWarning1 = getContrastRatio('#0f172a', '#ff6a00');
    assert.ok(contrastBtnWarning1 >= 4.5, `Ratio btn-warning 1: ${contrastBtnWarning1} debe ser >= 4.5`);
    const contrastBtnWarning2 = getContrastRatio('#0f172a', '#d97706');
    assert.ok(contrastBtnWarning2 >= 4.5, `Ratio btn-warning 2: ${contrastBtnWarning2} debe ser >= 4.5`);

    // 5. --text-muted ajustado en tema sena (#466146) sobre fondo base (#f0f7ec)
    const contrastMutedSena = getContrastRatio('#466146', '#f0f7ec');
    assert.ok(contrastMutedSena >= 4.5, `Ratio muted sena: ${contrastMutedSena} debe ser >= 4.5`);

    // 6. Texto sobre fondo oscuro en tema ocean/dark (#0e1a2e)
    const contrastVerdeOscuro = getContrastRatio('#4ade80', '#0e1a2e');
    assert.ok(contrastVerdeOscuro >= 4.5, `Ratio verde oscuro: ${contrastVerdeOscuro} debe ser >= 4.5`);
    const contrastAzulOscuro = getContrastRatio('#38bdf8', '#0e1a2e');
    assert.ok(contrastAzulOscuro >= 4.5, `Ratio azul oscuro: ${contrastAzulOscuro} debe ser >= 4.5`);
});

test('estandarización de foco de teclado universal con :focus-visible accesible', () => {
    // Debe incluir outline de 3px sólido con offset de 2px
    assert.match(stylesCss, /outline:\s*3px\s+solid\s+var\(--accent-primary\)\s*!important/);
    assert.match(stylesCss, /outline-offset:\s*2px\s*!important/);

    // En modal-system.css también debe haber outline de 3px con outline-offset
    assert.match(modalCss, /outline:\s*3px\s+solid\s+var\(--accent-primary\)\s*!important/);
    assert.match(modalCss, /outline-offset:\s*2px\s*!important/);
});

// ---------------------------------------------------------------------------
// SISTEMA VISUAL 2.0 — superficies translúcidas y contraste compuesto por alfa
// ---------------------------------------------------------------------------

// Extrae todas las reglas con sus declaraciones respetando llaves anidadas.
function bloquesCss(css) {
    // Los comentarios se sustituyen por espacios para no confundir cabeceras.
    const limpio = css.replace(/\/\*[\s\S]*?\*\//g, comentario => ' '.repeat(comentario.length));
    const bloques = [];
    let cursor = 0;
    while (cursor < limpio.length) {
        const apertura = limpio.indexOf('{', cursor);
        if (apertura === -1) break;
        const cierrePrevio = Math.max(limpio.lastIndexOf('}', apertura), limpio.lastIndexOf(';', apertura));
        const cabecera = limpio.slice(cierrePrevio + 1, apertura).trim();
        let profundidad = 0;
        let fin = apertura;
        for (; fin < limpio.length; fin += 1) {
            if (limpio[fin] === '{') profundidad += 1;
            else if (limpio[fin] === '}') {
                profundidad -= 1;
                if (profundidad === 0) break;
            }
        }
        bloques.push({ cabecera, cuerpo: limpio.slice(apertura + 1, fin) });
        cursor = fin + 1;
    }
    return bloques;
}

function declaraciones(bloques) {
    const mapa = new Map();
    for (const bloque of bloques) {
        for (const coincidencia of bloque.cuerpo.matchAll(/(--[a-zA-Z0-9_-]+)\s*:\s*([^;]+);/g)) {
            mapa.set(coincidencia[1], coincidencia[2].trim());
        }
    }
    return mapa;
}

const BLOQUES_CSS = bloquesCss(stylesCss);
const PRIMITIVOS = declaraciones(BLOQUES_CSS.filter(bloque => bloque.cabecera === ':root'));

function declaracionesTema(selectores) {
    const mapa = new Map(PRIMITIVOS);
    const relevantes = BLOQUES_CSS.filter(bloque =>
        selectores.some(selector => bloque.cabecera.includes(selector))
    );
    for (const [nombre, valor] of declaraciones(relevantes)) mapa.set(nombre, valor);
    return mapa;
}

const TEMAS = {
    elegante: declaracionesTema(['[data-theme="elegant"]', '[data-theme="light"]']),
    sena: declaracionesTema(['[data-theme="sena"]']),
    ocean: declaracionesTema(['[data-theme="ocean"]', '[data-theme="dark"]']),
};

// Resuelve una referencia var(...) hasta dos pasadas, como hace el navegador.
function resolverValor(valor, mapa, pasadas = 0) {
    const referencia = /^var\(\s*(--[a-zA-Z0-9_-]+)\s*(?:,\s*([\s\S]+))?\)$/.exec(valor.trim());
    if (!referencia) return valor;
    const [, nombre, respaldo] = referencia;
    if (mapa.has(nombre) && pasadas < 2) return resolverValor(mapa.get(nombre), mapa, pasadas + 1);
    if (respaldo) return resolverValor(respaldo, mapa, pasadas + 1);
    throw new Error(`No se pudo resolver ${valor} con los tokens del tema`);
}

function parsearCanal(valor) {
    const numero = Number.parseFloat(valor);
    if (Number.isNaN(numero)) throw new Error(`Canal de color inválido: ${valor}`);
    return numero;
}

function parsearColor(valor) {
    const limpio = valor.trim().toLowerCase();
    const hex = /^#([0-9a-f]{3,8})$/.exec(limpio);
    if (hex) {
        const cadena = hex[1].length === 3
            ? hex[1].split('').map(caracter => caracter + caracter).join('')
            : hex[1];
        const alfa = cadena.length === 8 ? parseInt(cadena.slice(6, 8), 16) / 255 : 1;
        return {
            r: parseInt(cadena.slice(0, 2), 16),
            g: parseInt(cadena.slice(2, 4), 16),
            b: parseInt(cadena.slice(4, 6), 16),
            a: alfa,
        };
    }
    const funcional = /^rgba?\(([^)]+)\)$/.exec(limpio);
    if (funcional) {
        const partes = funcional[1].split(/[,/]/).map(parte => parte.trim()).filter(Boolean);
        if (partes.length < 3) throw new Error(`Color rgb con canales insuficientes: ${valor}`);
        return {
            r: parsearCanal(partes[0]),
            g: parsearCanal(partes[1]),
            b: parsearCanal(partes[2]),
            a: partes.length > 3 ? parsearCanal(partes[3]) : 1,
        };
    }
    throw new Error(`Formato de color no soportado por la prueba: ${valor}`);
}

// Composición "source-over" de un color con alfa sobre una superficie opaca.
function componerSobre(color, fondo) {
    const alfa = color.a;
    if (alfa >= 1) return { r: color.r, g: color.g, b: color.b, a: 1 };
    const mezclar = (frente, atras) => frente * alfa + atras * (1 - alfa);
    return {
        r: mezclar(color.r, fondo.r),
        g: mezclar(color.g, fondo.g),
        b: mezclar(color.b, fondo.b),
        a: 1,
    };
}

function luminancia(color) {
    return 0.2126 * srgbToLinear(color.r) + 0.7152 * srgbToLinear(color.g) + 0.0722 * srgbToLinear(color.b);
}

function contrasteEntre(colorA, colorB) {
    const lumA = luminancia(colorA);
    const lumB = luminancia(colorB);
    const claro = Math.max(lumA, lumB);
    const oscuro = Math.min(lumA, lumB);
    return (claro + 0.05) / (oscuro + 0.05);
}

function tokenDeColor(mapa, nombre, tema) {
    if (!mapa.has(nombre)) throw new Error(`Falta ${nombre} en el tema ${tema}`);
    return parsearColor(resolverValor(mapa.get(nombre), mapa));
}

test('tokens de superficie, borde y control definidos en los tres temas', () => {
    const requeridos = [
        '--surface-glass',
        '--surface-glass-strong',
        '--surface-data',
        '--surface-control',
        '--border-glass',
        '--border-control',
        '--radius-md',
        '--radius-control',
        '--control-h-sm',
        '--bg-base',
        '--text-strong',
        '--text-main',
        '--text-muted',
    ];
    for (const [tema, mapa] of Object.entries(TEMAS)) {
        assert.ok(mapa.size > 0, `No se pudo leer el tema ${tema}`);
        for (const token of requeridos) {
            assert.ok(mapa.has(token), `El tema ${tema} debe definir ${token}`);
        }
    }
    // Los tokens de superficie deben declararse dentro del bloque del tema, no
    // solo heredarse, para que cada tema pueda calibrar su propia translucidez.
    for (const selectores of [['[data-theme="elegant"]'], ['[data-theme="sena"]'], ['[data-theme="ocean"]']]) {
        const bloquesTema = BLOQUES_CSS.filter(bloque => selectores.some(selector => bloque.cabecera.includes(selector)));
        const mapa = declaraciones(bloquesTema);
        for (const token of ['--surface-glass', '--surface-glass-strong', '--surface-data', '--surface-control', '--border-glass', '--border-control']) {
            assert.ok(mapa.has(token), `${selectores[0]} debe declarar ${token} en su propio bloque`);
        }
    }
});

test('contraste compuesto de las superficies translúcidas sobre --bg-base (AA)', () => {
    for (const [tema, mapa] of Object.entries(TEMAS)) {
        const fondo = tokenDeColor(mapa, '--bg-base', tema);
        const vidrio = tokenDeColor(mapa, '--surface-glass', tema);
        const compuesto = componerSobre(vidrio, fondo);

        for (const texto of ['--text-strong', '--text-main', '--text-muted']) {
            const ratio = contrasteEntre(tokenDeColor(mapa, texto, tema), compuesto);
            assert.ok(
                ratio >= 4.5,
                `${tema}: ${texto} sobre --surface-glass compuesto da ${ratio.toFixed(2)} (mínimo 4.5)`
            );
        }

        const ratioBorde = contrasteEntre(tokenDeColor(mapa, '--border-control', tema), compuesto);
        assert.ok(
            ratioBorde >= 3.0,
            `${tema}: --border-control sobre --surface-glass compuesto da ${ratioBorde.toFixed(2)} (mínimo 3.0)`
        );
    }
});

test('fallbacks de vidrio: @supports not, transparencia reducida, contraste y colores forzados', () => {
    const css = stylesCss + '\n' + modalCss;
    assert.match(css, /@supports\s+not\s*\(/, 'debe existir el fallback @supports not para navegadores sin backdrop-filter');
    assert.match(css, /@media\s*\(prefers-reduced-transparency:\s*reduce\)/, 'debe existir @media (prefers-reduced-transparency: reduce)');
    assert.match(css, /@media\s*\(prefers-contrast:\s*more\)/, 'debe existir @media (prefers-contrast: more)');
    assert.match(css, /@media\s*\(forced-colors:\s*active\)/, 'debe existir @media (forced-colors: active)');
});

test('estados canónicos de botón y variantes outline accesibles', () => {
    for (const selector of [
        '.btn:disabled',
        '.btn[aria-disabled="true"]',
        '.btn[aria-busy="true"]',
        '.btn-icon',
        '.btn-ghost',
        '.btn-outline-danger',
        '.btn-outline-success',
    ]) {
        assert.ok(stylesCss.includes(selector), `styles.css debe definir ${selector}`);
    }
});

test('dimensiones mínimas táctiles (>= 42px y >= 44px en modales y controles clave)', () => {
    // 1. .btn base y .btn-sm
    assert.match(stylesCss, /\.btn\s*\{[\s\S]*?min-height:\s*42px/);
    assert.match(stylesCss, /\.btn-sm\s*\{[\s\S]*?min-height:\s*42px/);
    assert.match(stylesCss, /\.btn-sm\s*\{[\s\S]*?min-width:\s*42px/);

    // 2. .alert-close-btn
    assert.match(stylesCss, /\.alert-close-btn\s*\{[\s\S]*?min-height:\s*42px/);
    assert.match(stylesCss, /\.alert-close-btn\s*\{[\s\S]*?min-width:\s*42px/);

    // 3. .nav-icon-button base y adaptaciones
    assert.match(stylesCss, /\.nav-icon-button\s*\{[\s\S]*?width:\s*42px/);
    assert.match(stylesCss, /\.nav-icon-button\s*\{[\s\S]*?height:\s*42px/);

    // 4. .btn-back y .back-link
    assert.match(stylesCss, /\.btn-back,[\s\S]*?\.back-link\s*\{[\s\S]*?min-height:\s*42px/);

    // 5. .app-modal-close y controles de modal en modal-system.css
    assert.match(modalCss, /\.app-modal-close[\s\S]*?min-height:\s*44px/);
    assert.match(modalCss, /\.app-modal-close\s*\{[\s\S]*?width:\s*44px/);
    assert.match(modalCss, /\.app-modal-close\s*\{[\s\S]*?height:\s*44px/);
    assert.match(modalCss, /\.app-notice-close\s*\{[\s\S]*?width:\s*44px/);
});
