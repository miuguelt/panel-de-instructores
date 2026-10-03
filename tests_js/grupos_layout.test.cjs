const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const plantillaPath = path.resolve(__dirname, '../app/templates/grupos/listar_grupos.html');

test('el panel del generador apila el encabezado y el formulario', () => {
    const plantilla = fs.readFileSync(plantillaPath, 'utf8');
    const reglaSidebar = plantilla.match(/\.bento-sidebar\s*\{([^}]+)\}/);

    assert.ok(reglaSidebar, 'la plantilla debe definir los estilos del panel del generador');
    assert.match(reglaSidebar[1], /display\s*:\s*flex\s*;/);
    assert.match(reglaSidebar[1], /flex-direction\s*:\s*column\s*;/);
});

test('la plantilla de grupos carga Lucide localmente y no llama lucide desnudo en el arranque', () => {
    const plantilla = fs.readFileSync(plantillaPath, 'utf8');
    assert.match(plantilla, /vendor\/lucide\/lucide\.min\.js/, 'debe cargar Lucide desde vendor local');
    assert.doesNotMatch(plantilla, /https:\/\/unpkg\.com\/lucide/, 'no debe depender directamente de unpkg');
    // Verificar que no se ejecute un lucide.createIcons() suelto en el arranque del bloque script
    const scriptMatch = plantilla.match(/<script>([\s\S]*?)<\/script>/);
    assert.ok(scriptMatch, 'debe contener bloque script');
    const inicioScript = scriptMatch[1].slice(0, 100);
    assert.doesNotMatch(inicioScript, /^\s*lucide\.createIcons\(\);/m, 'no debe llamar lucide.createIcons() desnudo al inicio del script');
});

test('los botones de edición y medalla usan data attributes seguros y exponen sus funciones en window', () => {
    const plantilla = fs.readFileSync(plantillaPath, 'utf8');
    assert.match(plantilla, /data-grupo-id=/, 'debe incluir data-grupo-id en el botón de edición');
    assert.match(plantilla, /data-grupo-nombre=/, 'debe incluir data-grupo-nombre en el botón de edición');
    assert.match(plantilla, /data-miembros=/, 'debe incluir data-miembros en el botón de edición');
    assert.match(plantilla, /window\.abrirModalEditarGrupo\s*=/, 'debe exponer abrirModalEditarGrupo en window');
    assert.match(plantilla, /window\.abrirModalCrearGrupo\s*=/, 'debe exponer abrirModalCrearGrupo en window');
    assert.match(plantilla, /window\.abrirModalInsignia\s*=/, 'debe exponer abrirModalInsignia en window');
});

