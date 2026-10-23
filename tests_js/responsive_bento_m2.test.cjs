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

    // El tema Sena calibra su superficie translúcida (alfa 0.74–0.86) y el texto
    // principal conserva contraste AA sobre el color compuesto, no sobre el ideal.
    const bloquesSena = [...stylesCss.matchAll(/\[data-theme="sena"\][^{}]*\{([^}]*)\}/g)]
        .map(coincidencia => coincidencia[1])
        .filter(cuerpo => /--surface-glass\s*:/.test(cuerpo));
    assert.ok(bloquesSena.length > 0, 'el tema Sena debe declarar --surface-glass en su bloque de tokens');

    const token = (cuerpo, nombre) => {
        const coincidencia = new RegExp(nombre + '\\s*:\\s*([^;]+);').exec(cuerpo);
        return coincidencia ? coincidencia[1].trim() : null;
    };

    const colorDesdeCss = (valor) => {
        const hex = /^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/.exec(valor);
        if (hex) {
            const cadena = hex[1].length === 3
                ? hex[1].split('').map(c => c + c).join('')
                : hex[1];
            return {
                r: parseInt(cadena.slice(0, 2), 16),
                g: parseInt(cadena.slice(2, 4), 16),
                b: parseInt(cadena.slice(4, 6), 16),
                a: 1,
            };
        }
        const rgba = /^rgba?\(([^)]+)\)$/.exec(valor);
        assert.ok(rgba, `Color no reconocido en el tema Sena: ${valor}`);
        const partes = rgba[1].split(',').map(parte => Number.parseFloat(parte.trim()));
        return { r: partes[0], g: partes[1], b: partes[2], a: partes.length > 3 ? partes[3] : 1 };
    };

    const luminancia = (color) => {
        const canal = (valor) => {
            const v = valor / 255;
            return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
        };
        return 0.2126 * canal(color.r) + 0.7152 * canal(color.g) + 0.0722 * canal(color.b);
    };

    const contraste = (a, b) => {
        const la = luminancia(a);
        const lb = luminancia(b);
        return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
    };

    let comprobado = false;
    for (const cuerpo of bloquesSena) {
        const vidrio = token(cuerpo, '--surface-glass');
        const fondo = token(cuerpo, '--bg-base');
        const texto = token(cuerpo, '--text-main');
        if (!vidrio || !fondo || !texto) continue;
        comprobado = true;

        const colorVidrio = colorDesdeCss(vidrio);
        assert.ok(
            colorVidrio.a >= 0.74 && colorVidrio.a <= 0.86,
            `[data-theme="sena"] --surface-glass debe tener alfa entre 0.74 y 0.86 (actual ${colorVidrio.a})`
        );

        const colorFondo = colorDesdeCss(fondo);
        const compuesto = {
            r: colorVidrio.r * colorVidrio.a + colorFondo.r * (1 - colorVidrio.a),
            g: colorVidrio.g * colorVidrio.a + colorFondo.g * (1 - colorVidrio.a),
            b: colorVidrio.b * colorVidrio.a + colorFondo.b * (1 - colorVidrio.a),
            a: 1,
        };
        const ratio = contraste(colorDesdeCss(texto), compuesto);
        assert.ok(
            ratio >= 4.5,
            `[data-theme="sena"] --text-main sobre --surface-glass compuesto da ${ratio.toFixed(2)} (mínimo 4.5)`
        );
    }
    assert.ok(comprobado, 'No se pudo componer --surface-glass sobre --bg-base en el tema Sena');
});

test('F09: reorganización de cuadrículas densas en pantallas móviles ultraestrechas', () => {
    // .vision-recommendations-grid utiliza límite inferior fluido min(100%, 280px)
    assert.match(stylesCss, /\.vision-recommendations-grid\s*\{[\s\S]*?grid-template-columns:\s*repeat\(auto-fit,\s*minmax\(min\(100%,\s*280px\),\s*1fr\)\);/);

    // .followup-settings-grid se adapta a 1 columna en <= 420px
    assert.match(stylesCss, /@media\s*\(max-width:\s*420px\)\s*\{[\s\S]*?\.followup-settings-grid[\s\S]*?grid-template-columns:\s*1fr;/);

    // .pl-eval-metricas se adapta a 1 columna en pantallas ultraestrechas (<= 420px)
    assert.match(planEvalCss, /@media\s*\(max-width:\s*420px\)\s*\{[\s\S]*?\.pl-eval-metricas\s*\{[\s\S]*?grid-template-columns:\s*1fr;/);
});
