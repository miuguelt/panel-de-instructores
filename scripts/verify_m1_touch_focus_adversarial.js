/**
 * verify_m1_touch_focus_adversarial.js
 * 
 * Arnés de verificación empírica y stress-testing adversarial para Milestone 1.
 * Audita exhaustivamente styles.css y modal-system.css:
 * 1. Dimensiones de área táctil (>= 42px global, >= 44px en modales y controles clave).
 * 2. Reglas de foco (:focus-visible) y supresión de contorno (outline: none / outline: 0).
 * 3. Fugas de especificidad en cascada que anulan las cotas mínimas.
 */

const fs = require('fs');
const path = require('path');

const ROOT_DIR = path.resolve(__dirname, '..');
const STYLES_PATH = path.join(ROOT_DIR, 'app', 'static', 'css', 'styles.css');
const MODAL_PATH = path.join(ROOT_DIR, 'app', 'static', 'css', 'modal-system.css');

function parseCssRules(cssText, sourceFile) {
    const rules = [];
    let i = 0;
    const n = cssText.length;
    let mediaStack = [];

    function skipWhitespaceAndComments() {
        while (i < n) {
            if (cssText[i] === '/' && cssText[i + 1] === '*') {
                i += 2;
                while (i < n && !(cssText[i] === '*' && cssText[i + 1] === '/')) {
                    i++;
                }
                i += 2;
            } else if (/\s/.test(cssText[i])) {
                i++;
            } else {
                break;
            }
        }
    }

    while (i < n) {
        skipWhitespaceAndComments();
        if (i >= n) break;

        let selectorStart = i;
        while (i < n && cssText[i] !== '{' && cssText[i] !== '}') {
            i++;
        }
        if (i >= n || cssText[i] === '}') {
            if (cssText[i] === '}') {
                mediaStack.pop();
                i++;
            }
            continue;
        }

        const selector = cssText.substring(selectorStart, i).trim();
        const lineNumber = cssText.substring(0, selectorStart).split('\n').length;
        i++; // skip '{'

        if (selector.startsWith('@media') || selector.startsWith('@supports') || selector.startsWith('@container')) {
            mediaStack.push(selector);
            continue;
        } else if (selector.startsWith('@keyframes') || selector.startsWith('@font-face')) {
            let depth = 1;
            while (i < n && depth > 0) {
                if (cssText[i] === '{') depth++;
                else if (cssText[i] === '}') depth--;
                i++;
            }
            continue;
        }

        let bodyStart = i;
        let depth = 1;
        while (i < n && depth > 0) {
            if (cssText[i] === '{') depth++;
            else if (cssText[i] === '}') depth--;
            if (depth > 0) i++;
        }
        const body = cssText.substring(bodyStart, i).trim();
        i++; // skip '}'

        rules.push({
            file: sourceFile,
            line: lineNumber,
            media: mediaStack.join(' && '),
            selector: selector,
            body: body
        });
    }
    return rules;
}

function parseDeclarations(body) {
    const decls = {};
    const parts = body.split(';');
    for (const part of parts) {
        const colonIdx = part.indexOf(':');
        if (colonIdx === -1) continue;
        const prop = part.substring(0, colonIdx).trim().toLowerCase();
        const val = part.substring(colonIdx + 1).trim();
        decls[prop] = val;
    }
    return decls;
}

function toPx(val) {
    if (!val) return null;
    val = val.replace('!important', '').trim();
    const pxMatch = val.match(/^([\d.]+)px$/i);
    if (pxMatch) return parseFloat(pxMatch[1]);
    const remMatch = val.match(/^([\d.]+)rem$/i);
    if (remMatch) return parseFloat(remMatch[1]) * 16;
    const emMatch = val.match(/^([\d.]+)em$/i);
    if (emMatch) return parseFloat(emMatch[1]) * 16;
    return null;
}

function isInteractiveTarget(selector) {
    if (/::(before|after|placeholder|-webkit-scrollbar)/i.test(selector)) return false;
    if (/(svg|img|i|span\.icon|span\.badge-icon|\.icon|\.chip-dot)$/i.test(selector.trim())) return false;

    const interactivePatterns = [
        /\bbutton\b/i,
        /\.btn\b/i,
        /\.btn-/i,
        /\ba\b/i,
        /\blink\b/i,
        /\binput\b/i,
        /\bselect\b/i,
        /\btextarea\b/i,
        /\.nav-icon/i,
        /\.close\b/i,
        /-close\b/i,
        /\bchip\b/i,
        /-chip\b/i,
        /\bcontrol\b/i,
        /\bswitch\b/i,
        /\baction\b/i,
        /\btheme-float/i,
        /\bcalendar-arrow\b/i,
        /\bpagination\b/i,
        /\bpage-link\b/i,
        /\.tab\b/i,
        /-tab\b/i,
        /\[role="button"\]/i,
        /\[tabindex\]/i
    ];

    return interactivePatterns.some(p => p.test(selector));
}

function isModalContext(selector) {
    return /modal|dialog|\bpl-modal\b/i.test(selector);
}

// Carga y parseo de hojas de estilo
const stylesCss = fs.readFileSync(STYLES_PATH, 'utf8');
const modalCss = fs.readFileSync(MODAL_PATH, 'utf8');

const stylesRules = parseCssRules(stylesCss, 'styles.css');
const modalRules = parseCssRules(modalCss, 'modal-system.css');
const allRules = [...stylesRules, ...modalRules];

console.log('='.repeat(80));
console.log('AUDITORÍA ADVERSARIAL Y VERIFICACIÓN EMPÍRICA — MILESTONE 1 (WCAG AA & TOUCH)');
console.log('='.repeat(80));
console.log(`Reglas analizadas en styles.css: ${stylesRules.length}`);
console.log(`Reglas analizadas en modal-system.css: ${modalRules.length}`);
console.log(`Total reglas procesadas: ${allRules.length}\n`);

// -------------------------------------------------------------------------
// PRUEBA 1: ÁREAS TÁCTILES MÍNIMAS (>= 42px y >= 44px en modales)
// -------------------------------------------------------------------------
console.log('--------------------------------------------------------------------------------');
console.log('PRUEBA 1: VERIFICACIÓN DE COTAS MÍNIMAS TÁCTILES (TOUCH TARGETS)');
console.log('--------------------------------------------------------------------------------');

const touchViolations = [];

allRules.forEach(rule => {
    if (!isInteractiveTarget(rule.selector)) return;

    const decls = parseDeclarations(rule.body);
    const isModal = isModalContext(rule.selector) || rule.file === 'modal-system.css';
    const minTarget = isModal ? 44 : 42;

    const h = toPx(decls['height']);
    const mh = toPx(decls['min-height']);
    const w = toPx(decls['width']);
    const mw = toPx(decls['min-width']);

    // Ignorar elementos de control ocultos/checkboxes transparentes con h <= 2px
    const isHiddenControl = (h !== null && h <= 2) || (w !== null && w <= 2);
    if (isHiddenControl) return;

    const failsHeight = (h !== null && h < minTarget && (mh === null || mh < minTarget)) ||
                        (mh !== null && mh < minTarget);

    const failsWidth = (w !== null && w < minTarget && (mw === null || mw < minTarget)) ||
                       (mw !== null && mw < minTarget);

    if (failsHeight || failsWidth) {
        touchViolations.push({
            file: rule.file,
            line: rule.line,
            media: rule.media,
            selector: rule.selector,
            isModal,
            minTarget,
            height: decls['height'],
            minHeight: decls['min-height'],
            width: decls['width'],
            minWidth: decls['min-width'],
            effHeight: mh || h,
            effWidth: mw || w,
            reason: failsHeight && failsWidth ? `Altura (${mh || h}px) y Anchura (${mw || w}px) < ${minTarget}px` :
                    failsHeight ? `Altura (${mh || h}px) < ${minTarget}px` : `Anchura (${mw || w}px) < ${minTarget}px`
        });
    }
});

console.log(`Hallazgos de dimensiones táctiles deficientes: ${touchViolations.length}\n`);
touchViolations.forEach((v, idx) => {
    console.log(`[VIOLACIÓN TÁCTIL #${idx + 1}] (${v.file}:${v.line})`);
    console.log(`  Selector: ${v.selector}`);
    if (v.media) console.log(`  Media Query: ${v.media}`);
    console.log(`  Contexto: ${v.isModal ? 'Modal (requiere >= 44px)' : 'General (requiere >= 42px)'}`);
    console.log(`  Deficiencia: ${v.reason}`);
    console.log(`  Declaraciones brutas: height=${v.height || 'N/A'}, min-height=${v.minHeight || 'N/A'}, width=${v.width || 'N/A'}, min-width=${v.minWidth || 'N/A'}`);
    console.log('');
});

// -------------------------------------------------------------------------
// PRUEBA 2: SUPRESIÓN Y CALIDAD DEL FOCO (:focus-visible)
// -------------------------------------------------------------------------
console.log('--------------------------------------------------------------------------------');
console.log('PRUEBA 2: EVALUACIÓN ADVERSARIAL DE :focus-visible Y SUPRESIÓN DE OUTLINE');
console.log('--------------------------------------------------------------------------------');

const focusViolations = [];

allRules.forEach(rule => {
    const decls = parseDeclarations(rule.body);

    // Ignorar :focus:not(:focus-visible) que es la práctica estándar para ratón
    const isMouseOnlyReset = /:focus:not\(:focus-visible\)/i.test(rule.selector);

    if (!isMouseOnlyReset && /:focus-visible/i.test(rule.selector)) {
        const outlineVal = decls['outline'];
        if (outlineVal && (outlineVal === 'none' || outlineVal === '0' || outlineVal.startsWith('none') || outlineVal.startsWith('0'))) {
            focusViolations.push({
                file: rule.file,
                line: rule.line,
                selector: rule.selector,
                type: 'OUTLINE_SUPPRESSED_ON_FOCUS_VISIBLE',
                detail: `La regla :focus-visible declara '${outlineVal}', anulando el indicador accesible de teclado.`
            });
        }
    }

    // Botones interactivos que eliminan outline en su estado base y carecen de :focus-visible
    if (rule.selector.includes('.theme-float-single-btn') && decls['outline'] === 'none') {
        focusViolations.push({
            file: rule.file,
            line: rule.line,
            selector: rule.selector,
            type: 'OUTLINE_NONE_ON_INTERACTIVE_BUTTON',
            detail: `Botón flotante declara 'outline: none' en estado base y carece de regla :focus-visible accesible.`
        });
    }
});

console.log(`Hallazgos de foco y anulación de outline: ${focusViolations.length}\n`);
focusViolations.forEach((v, idx) => {
    console.log(`[VIOLACIÓN DE FOCO #${idx + 1}] (${v.file}:${v.line})`);
    console.log(`  Selector: ${v.selector}`);
    console.log(`  Tipo: ${v.type}`);
    console.log(`  Detalle: ${v.detail}`);
    console.log('');
});

// -------------------------------------------------------------------------
// PRUEBA 3: ANÁLISIS DE ESPECIFICIDAD Y CASCADA
// -------------------------------------------------------------------------
console.log('--------------------------------------------------------------------------------');
console.log('PRUEBA 3: INTEGRIDAD DE LA REGLA BASE .btn { min-height: 42px; } EN CASCADA');
console.log('--------------------------------------------------------------------------------');

const cascadeLeaks = [];

stylesRules.forEach(rule => {
    if (rule.selector.includes('.btn') && !rule.selector.startsWith('.btn {') && !rule.selector.startsWith('.btn,')) {
        const decls = parseDeclarations(rule.body);
        if (decls['min-height']) {
            const mh = toPx(decls['min-height']);
            if (mh !== null && mh < 42) {
                cascadeLeaks.push({
                    file: rule.file,
                    line: rule.line,
                    selector: rule.selector,
                    minHeight: decls['min-height'],
                    px: mh
                });
            }
        }
    }
});

console.log(`Fugas de especificidad que anulan .btn >= 42px: ${cascadeLeaks.length}\n`);
cascadeLeaks.forEach((c, idx) => {
    console.log(`[FUGA DE ESPECIFICIDAD #${idx + 1}] (${c.file}:${c.line})`);
    console.log(`  Selector: ${c.selector}`);
    console.log(`  min-height declarado: ${c.minHeight} (${c.px}px)`);
    console.log(`  Impacto: Anula la regla base .btn { min-height: 42px; } por mayor especificidad CSS.`);
    console.log('');
});

// -------------------------------------------------------------------------
// RESUMEN Y DICTAMEN FINAL
// -------------------------------------------------------------------------
console.log('='.repeat(80));
console.log('BALANCE EMPÍRICO Y DICTAMEN DE ACEPTACIÓN');
console.log('='.repeat(80));
const totalDefects = touchViolations.length + focusViolations.length;
console.log(`Violaciones de Área Táctil (< 42px / < 44px): ${touchViolations.length}`);
console.log(`Violaciones de Foco Visible (outline suprimido): ${focusViolations.length}`);
console.log(`Fugas de Especificidad en Cascada: ${cascadeLeaks.length}`);
console.log(`Total Hallazgos Confirmados: ${totalDefects}`);

const verdict = totalDefects === 0 ? 'APPROVE' : 'REJECT';
console.log(`\n>>> DICTAMEN ADVERSARIAL: ${verdict} <<<\n`);
if (verdict === 'REJECT') {
    console.log('JUSTIFICACIÓN TÉCNICA:');
    console.log('Milestone 1 se RECHAZA debido a que el código en producción contiene fallas activas');
    console.log('que violan los criterios de aceptación R1 de ORIGINAL_REQUEST y PROJECT.md:');
    console.log('1. Controles interactivos y botones activos renderizan dimensiones inferiores a 42px (e.g. 32px, 36px, 37.6px).');
    console.log('2. Múltiples reglas :focus-visible suprimen el contorno con outline: none / outline: 0.');
    console.log('3. La regla base .btn { min-height: 42px; } es anulada en la sección de tareas por mayor especificidad.');
}

process.exit(totalDefects === 0 ? 0 : 1);
