/**
 * Script de Verificación Empírica y Adversarial de Contraste WCAG 2.1 AA
 * Challenger Milestone 1 - Panel de Instructores SENA Control
 *
 * Parsea directamente app/static/css/styles.css y app/static/css/modal-system.css,
 * extrae variables CSS por tema y reglas de componentes, computa luminancias sRGB W3C
 * y evalúa el cumplimiento de ratios WCAG 2.1 AA (4.5:1 para texto normal, 3.0:1 para componentes/texto grande).
 */

const fs = require('node:fs');
const path = require('node:path');

const stylesPath = path.join(__dirname, '..', 'app', 'static', 'css', 'styles.css');
const modalStylesPath = path.join(__dirname, '..', 'app', 'static', 'css', 'modal-system.css');

const stylesCss = fs.readFileSync(stylesPath, 'utf8');
const modalCss = fs.readFileSync(modalStylesPath, 'utf8');

// ==========================================
// 1. FÓRMULAS OFICIALES W3C WCAG 2.1
// ==========================================
function srgbToLinear(c) {
    const v = c / 255;
    return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
}

function parseColor(str) {
    if (!str) return null;
    str = str.trim();
    if (str.startsWith('#')) {
        let clean = str.replace('#', '');
        if (clean.length === 3) {
            return {
                r: parseInt(clean[0] + clean[0], 16),
                g: parseInt(clean[1] + clean[1], 16),
                b: parseInt(clean[2] + clean[2], 16),
                a: 1.0
            };
        }
        return {
            r: parseInt(clean.substring(0, 2), 16),
            g: parseInt(clean.substring(2, 4), 16),
            b: parseInt(clean.substring(4, 6), 16),
            a: 1.0
        };
    }
    const rgbaMatch = str.match(/rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)(?:\s*,\s*([\d.]+))?\s*\)/);
    if (rgbaMatch) {
        return {
            r: parseFloat(rgbaMatch[1]),
            g: parseFloat(rgbaMatch[2]),
            b: parseFloat(rgbaMatch[3]),
            a: rgbaMatch[4] !== undefined ? parseFloat(rgbaMatch[4]) : 1.0
        };
    }
    if (str.toLowerCase() === 'white') return { r: 255, g: 255, b: 255, a: 1.0 };
    if (str.toLowerCase() === 'black') return { r: 0, g: 0, b: 0, a: 1.0 };
    return null;
}

function compositeColor(fg, bg) {
    if (!fg) return bg;
    if (!bg) return fg;
    if (fg.a >= 1.0) return fg;
    return {
        r: Math.round(fg.r * fg.a + bg.r * (1 - fg.a)),
        g: Math.round(fg.g * fg.a + bg.g * (1 - fg.a)),
        b: Math.round(fg.b * fg.a + bg.b * (1 - fg.a)),
        a: 1.0
    };
}

function getLuminance(rgb) {
    return 0.2126 * srgbToLinear(rgb.r) + 0.7152 * srgbToLinear(rgb.g) + 0.0722 * srgbToLinear(rgb.b);
}

function getContrastRatio(rgb1, rgb2) {
    const l1 = getLuminance(rgb1);
    const l2 = getLuminance(rgb2);
    const lighter = Math.max(l1, l2);
    const darker = Math.min(l1, l2);
    return (lighter + 0.05) / (darker + 0.05);
}

// ==========================================
// 2. PARSEADOR DINÁMICO DE BLOQUES CSS
// ==========================================
function extractBlock(css, selectorRegex) {
    const match = css.match(selectorRegex);
    if (!match) return '';
    const start = match.index + match[0].length;
    let depth = 1;
    let end = start;
    while (end < css.length && depth > 0) {
        if (css[end] === '{') depth++;
        else if (css[end] === '}') depth--;
        end++;
    }
    return css.substring(start, end - 1);
}

function extractVariables(blockContent) {
    const vars = {};
    const regex = /(--[\w-]+)\s*:\s*([^;]+);/g;
    let m;
    while ((m = regex.exec(blockContent)) !== null) {
        vars[m[1].trim()] = m[2].trim();
    }
    return vars;
}

// Parsear variables globales y temáticas
const rootVars = extractVariables(extractBlock(stylesCss, /:root\s*\{/));
const elegantVars = { ...rootVars, ...extractVariables(extractBlock(stylesCss, /\[data-theme="elegant"\][^{]*\{/)) };
const senaVars = { ...rootVars, ...extractVariables(extractBlock(stylesCss, /\[data-theme="sena"\][^{]*\{/)) };
const oceanVars = { ...rootVars, ...extractVariables(extractBlock(stylesCss, /\[data-theme="ocean"\][^{]*\{/)) };

function resolveColor(varName, themeVars, fallback) {
    let val = themeVars[varName] || fallback;
    if (!val) return null;
    val = val.trim();
    // Resolver variables anidadas var(--algo, fallback)
    const varMatch = val.match(/^var\(\s*(--[\w-]+)(?:\s*,\s*([^)]+))?\s*\)$/);
    if (varMatch) {
        const nestedName = varMatch[1];
        const nestedFallback = varMatch[2] ? varMatch[2].trim() : null;
        return resolveColor(nestedName, themeVars, nestedFallback);
    }
    return val;
}

const themeData = [
    { key: 'elegant', name: 'Elegant (Light)', vars: elegantVars },
    { key: 'sena', name: 'SENA (Institucional)', vars: senaVars },
    { key: 'ocean', name: 'Ocean (Dark)', vars: oceanVars }
];

// ==========================================
// 3. MATRIZ DE VERIFICACIÓN EMPÍRICA
// ==========================================
const testResults = [];

function audit(themeKey, category, element, fgStr, bgStr, underlayStr, minRatio, isNonText = false, notes = '') {
    const fg = parseColor(fgStr);
    let bg = parseColor(bgStr);
    if (underlayStr && bg && bg.a < 1.0) {
        const underlay = parseColor(underlayStr);
        bg = compositeColor(bg, underlay);
    }

    if (!fg || !bg) {
        testResults.push({
            theme: themeKey,
            category,
            element,
            fgStr,
            bgStr,
            ratio: 0,
            required: minRatio,
            pass: false,
            error: 'No se pudo parsear el color'
        });
        return;
    }

    const ratio = parseFloat(getContrastRatio(fg, bg).toFixed(2));
    const pass = ratio >= minRatio;

    testResults.push({
        theme: themeKey,
        category,
        element,
        fgStr,
        bgStr,
        underlayStr,
        ratio,
        required: minRatio,
        pass,
        isNonText,
        notes
    });
}

for (const t of themeData) {
    const v = t.vars;
    const bgBase = resolveColor('--bg-base', v, '#ffffff');
    const bgSurface = resolveColor('--bg-surface', v, '#ffffff');
    const bgCardRaw = resolveColor('--bg-card', v, '#ffffff');
    const bgCard = parseColor(bgCardRaw).a < 1.0 ? compositeColor(parseColor(bgCardRaw), parseColor(bgBase)) : parseColor(bgCardRaw);
    const bgCardHex = `#${bgCard.r.toString(16).padStart(2,'0')}${bgCard.g.toString(16).padStart(2,'0')}${bgCard.b.toString(16).padStart(2,'0')}`;

    const textMain = resolveColor('--text-main', v, '#000000');
    const textStrong = resolveColor('--text-strong', v, '#000000');
    const textMuted = resolveColor('--text-muted', v, '#666666');

    const accentPrimary = resolveColor('--accent-primary', v, '#39A900');
    const accentHover = resolveColor('--accent-hover', v, '#2d8500');

    const succText = resolveColor('--status-success-text', v, '#166534');
    const succBg = resolveColor('--status-success-bg', v, 'rgba(22, 101, 52, 0.12)');
    const infoText = resolveColor('--status-info-text', v, '#1d4ed8');
    const infoBg = resolveColor('--status-info-bg', v, 'rgba(29, 78, 216, 0.12)');
    const warnText = resolveColor('--status-warning-text', v, '#7c2d12');
    const warnBg = resolveColor('--status-warning-bg', v, 'rgba(245, 158, 11, 0.14)');
    const dangText = resolveColor('--status-danger-text', v, '#991b1b');
    const dangBg = resolveColor('--status-danger-bg', v, 'rgba(239, 68, 68, 0.12)');

    const senaOrange = resolveColor('--sena-orange', v, '#ff6a00');
    const senaRed = resolveColor('--sena-red', v, '#ef4444');

    const badgeTechBg = resolveColor('--badge-tech-bg', v, '#2d8500');
    const badgeTechText = resolveColor('--badge-tech-text', v, '#ffffff');
    const badgeTransBg = resolveColor('--badge-transversal-bg', v, '#059669');
    const badgeTransText = resolveColor('--badge-transversal-text', v, '#ffffff');
    const badgeInglesBg = resolveColor('--badge-ingles-bg', v, '#0284c7');
    const badgeInglesText = resolveColor('--badge-ingles-text', v, '#ffffff');

    // 1. Textos Generales
    audit(t.key, 'Tipografía', '--text-main sobre --bg-card', textMain, bgCardHex, null, 4.5);
    audit(t.key, 'Tipografía', '--text-main sobre --bg-surface', textMain, bgSurface, null, 4.5);
    audit(t.key, 'Tipografía', '--text-main sobre --bg-base', textMain, bgBase, null, 4.5);

    audit(t.key, 'Tipografía', '--text-strong sobre --bg-card', textStrong, bgCardHex, null, 4.5);
    audit(t.key, 'Tipografía', '--text-strong sobre --bg-surface', textStrong, bgSurface, null, 4.5);
    audit(t.key, 'Tipografía', '--text-strong sobre --bg-base', textStrong, bgBase, null, 4.5);

    audit(t.key, 'Tipografía', '--text-muted sobre --bg-card', textMuted, bgCardHex, null, 4.5, false, 'Crítico: subtítulos y notas');
    audit(t.key, 'Tipografía', '--text-muted sobre --bg-surface', textMuted, bgSurface, null, 4.5);
    audit(t.key, 'Tipografía', '--text-muted sobre --bg-base', textMuted, bgBase, null, 4.5);

    // 2. Alertas Semánticas
    audit(t.key, 'Alertas', '.alert-success (texto sobre fondo compuesto)', succText, succBg, bgCardHex, 4.5);
    audit(t.key, 'Alertas', '.alert-info (texto sobre fondo compuesto)', infoText, infoBg, bgCardHex, 4.5);
    audit(t.key, 'Alertas', '.alert-warning (texto sobre fondo compuesto)', warnText, warnBg, bgCardHex, 4.5);
    audit(t.key, 'Alertas', '.alert-error (texto sobre fondo compuesto)', dangText, dangBg, bgCardHex, 4.5);

    // 3. Botones Interactivos
    // .btn-primary: background linear-gradient(135deg, accentHover, accentPrimary), color: white
    audit(t.key, 'Botones', '.btn-primary (color: white sobre --accent-primary)', '#ffffff', accentPrimary, null, 4.5, false, 'Botón primario');
    audit(t.key, 'Botones', '.btn-primary (color: white sobre --accent-hover)', '#ffffff', accentHover, null, 4.5, false, 'Botón primario hover');
    audit(t.key, 'Botones', '.btn-warning (texto #0f172a sobre #ff6a00)', '#0f172a', '#ff6a00', null, 4.5);
    audit(t.key, 'Botones', '.btn-warning (texto #0f172a sobre #d97706)', '#0f172a', '#d97706', null, 4.5);
    audit(t.key, 'Botones', '.btn-secondary (text-strong sobre border-divider)', textStrong, resolveColor('--border-divider', v, '#e8e8f0'), bgCardHex, 4.5);

    // 4. Badges e Insignias (font-size: 11px)
    audit(t.key, 'Badges', '.badge-success (white sobre sena-green-dark #2d8500)', '#ffffff', '#2d8500', null, 4.5);
    audit(t.key, 'Badges', '.badge-warning (#0f172a sobre sena-orange #ff6a00)', '#0f172a', senaOrange, null, 4.5);
    audit(t.key, 'Badges', '.badge-danger (white sobre sena-red #ef4444)', '#ffffff', senaRed, null, 4.5, false, 'Insignia de riesgo');
    audit(t.key, 'Badges', '.badge-info (white sobre #1d4ed8)', '#ffffff', '#1d4ed8', null, 4.5);
    audit(t.key, 'Badges', '.badge-tech', badgeTechText, badgeTechBg, null, 4.5);
    audit(t.key, 'Badges', '.badge-transversal', badgeTransText, badgeTransBg, null, 4.5);
    audit(t.key, 'Badges', '.badge-ingles', badgeInglesText, badgeInglesBg, null, 4.5);

    // 5. Indicador Universal de Foco (:focus-visible) - Criterio 1.4.11 (>= 3.0:1)
    // Regla: outline: 3px solid var(--accent-primary) !important;
    audit(t.key, 'Foco :focus-visible', 'outline accent-primary sobre --bg-card', accentPrimary, bgCardHex, null, 3.0, true);
    audit(t.key, 'Foco :focus-visible', 'outline accent-primary sobre --bg-surface', accentPrimary, bgSurface, null, 3.0, true);
    audit(t.key, 'Foco :focus-visible', 'outline accent-primary sobre --bg-base', accentPrimary, bgBase, null, 3.0, true);
}

// ==========================================
// 4. INFORME DE SALIDA EN CONSOLA Y ARCHIVO
// ==========================================
console.log('='.repeat(85));
console.log(' AUDITORÍA EMPÍRICA ADVERSARIAL DE CONTRASTE WCAG 2.1 AA — MILITARY GRADE TEST HARNESS');
console.log('='.repeat(85));

let passCount = 0;
let failCount = 0;
const failures = [];

for (const r of testResults) {
    const status = r.pass ? 'PASS' : 'FAIL';
    if (r.pass) {
        passCount++;
    } else {
        failCount++;
        failures.push(r);
    }
    const ratioStr = `${r.ratio.toFixed(2)}:1`.padStart(8);
    const reqStr = `>= ${r.required}:1`.padStart(9);
    console.log(`[${status}] [${r.theme.toUpperCase().padEnd(7)}] ${r.category.padEnd(18)} | ${r.element.padEnd(46)} | Ratio: ${ratioStr} (Exige: ${reqStr})`);
}

console.log('='.repeat(85));
console.log(`RESULTADO GLOBAL: ${testResults.length} pruebas | ${passCount} aprobadas | ${failCount} FALLIDAS`);
console.log(`VEREDICTO EMPÍRICO: ${failCount > 0 ? 'REJECT (RECHAZADO)' : 'APPROVE (APROBADO)'}`);
console.log('='.repeat(85));

if (failures.length > 0) {
    console.log('\nDETALLE DE DEFICIENCIAS DETECTADAS POR EL HARNESS ADVERSARIAL:');
    failures.forEach((f, idx) => {
        console.log(`${idx + 1}. [${f.theme.toUpperCase()}] ${f.category} -> ${f.element}`);
        console.log(`   Ratio obtenido: ${f.ratio}:1 vs Mínimo exigido: ${f.required}:1`);
        console.log(`   Colores en conflicto: FG=${f.fgStr} | BG=${f.bgStr}${f.underlayStr ? ` (sobre ${f.underlayStr})` : ''}`);
        if (f.notes) console.log(`   Nota: ${f.notes}`);
    });
}

// Guardar informe JSON para auditoría reproducible
const jsonOut = path.join(__dirname, '..', 'docs', 'wcag_audit_results.json');
try {
    fs.mkdirSync(path.dirname(jsonOut), { recursive: true });
    fs.writeFileSync(jsonOut, JSON.stringify({
        timestamp: new Date().toISOString(),
        verdict: failCount > 0 ? 'REJECT' : 'APPROVE',
        summary: { total: testResults.length, passed: passCount, failed: failCount },
        failures,
        results: testResults
    }, null, 2), 'utf8');
} catch (e) {
    console.error('Error guardando JSON:', e);
}

// Terminar con código de salida 1 si hay fallas para compuertas CI
if (require.main === module && failCount > 0) {
    process.exit(1);
}
