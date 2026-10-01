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
