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
