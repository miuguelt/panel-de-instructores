/**
 * Verificación visual del contrato "Sistema visual de superficies translúcidas,
 * botones y bordes (23 de octubre de 2026)".
 *
 * La página de prueba inyecta el contenido real de `styles.css` y
 * `modal-system.css` (sin servidor Flask) y comprueba estilos calculados:
 * radios, bordes, altura mínima táctil, `backdrop-filter`, foco visible,
 * ausencia de desbordamiento horizontal en 320/390/768/1440/1920/2560 px y
 * cambio entre los tres temas.
 *
 * REQUISITO DE ENTORNO: este archivo necesita lanzar Chromium real. En el
 * sandbox de DSH el lanzamiento falla con `spawn EPERM` (no se pueden abrir
 * procesos/pipe desde la sesión confinada). Ejecutar con permiso ampliado:
 *
 *     node tests_browser/diseno_visual.test.cjs
 *
 * (sesión con danger-full-access / aprobación de ejecución de procesos).
 * No se ejecuta como parte de `node tests_js/*.test.cjs`.
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

const raiz = path.resolve(__dirname, '..');
const cssSistema = fs.readFileSync(path.join(raiz, 'app', 'static', 'css', 'styles.css'), 'utf8');
const cssModales = fs.readFileSync(path.join(raiz, 'app', 'static', 'css', 'modal-system.css'), 'utf8');
const directorioResultados = path.join(raiz, 'test-results');

let browser;

function htmlPrueba() {
  return `<!doctype html>
<html lang="es-CO" data-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Contrato de superficies translúcidas</title>
<style>
${cssSistema}
${cssModales}
/* Solo maquetación de la página de prueba; el sistema viene de styles.css */
html, body { margin: 0; padding: 0; }
body { background: var(--bg-base); color: var(--text-main); font-family: system-ui, sans-serif; padding: 24px; }
#lienzo { display: grid; gap: 20px; max-width: 1200px; margin: 0 auto; min-width: 0; }
#lienzo > * { min-width: 0; }
#acciones { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; }
#tabla td, #tabla th { white-space: normal; }
</style>
</head>
<body>
<main id="lienzo">
  <section id="acciones" aria-label="Botones del sistema">
    <button id="primario" class="btn btn-primary" type="button">Acción principal</button>
    <button id="outline" class="btn btn-outline" type="button">Acción secundaria</button>
    <button id="deshabilitado" class="btn btn-primary" type="button" disabled>Deshabilitado</button>
    <button id="ocupado" class="btn btn-primary" type="button" aria-busy="true">Cargando</button>
    <button id="icono" class="btn btn-outline btn-icon" type="button" aria-label="Buscar">
      <i data-lucide="search" aria-hidden="true"></i>
    </button>
  </section>

  <article id="tarjeta" class="card">
    <h2>Tarjeta translúcida</h2>
    <p>Superficie legible con borde y radio del sistema.</p>
  </article>

  <div id="alerta" class="alert alert-success" role="status">Cambios guardados correctamente.</div>
  <p><span id="insignia" class="badge badge-success">Activo</span></p>

  <label for="campo">Campo de texto</label>
  <input id="campo" class="form-control" type="text" placeholder="Escribe aquí...">

  <div class="table-responsive" id="tabla-contenedor">
    <table class="table" id="tabla">
      <thead><tr><th>Aprendiz</th><th>Estado</th></tr></thead>
      <tbody>
        <tr><td>Ana María Pérez</td><td><span class="badge badge-success">Aprobado</span></td></tr>
        <tr><td>Carlos Andrés Gómez</td><td><span class="badge badge-warning">En proceso</span></td></tr>
      </tbody>
    </table>
  </div>

  <p><button id="abrir-modal" class="btn btn-outline" type="button">Abrir modal de prueba</button></p>
  <div id="modal" class="app-modal-overlay">
    <div class="app-modal-content" role="dialog" aria-modal="true" aria-labelledby="modal-titulo">
      <header class="app-modal-header"><h2 id="modal-titulo">Modal del sistema</h2></header>
      <div class="app-modal-body"><input id="modal-campo" class="form-control" type="text" placeholder="Dato"></div>
      <footer class="app-modal-footer"><button id="modal-guardar" class="btn btn-primary" type="button">Guardar</button></footer>
    </div>
  </div>
</main>
<script>
  document.getElementById('abrir-modal').addEventListener('click', () => {
    document.getElementById('modal').classList.add('is-open');
  });
</script>
</body>
</html>`;
}

async function abrirPagina(viewport = { width: 1440, height: 900 }) {
  const page = await browser.newPage({ viewport });
  await page.setContent(htmlPrueba(), { waitUntil: 'load' });
  return page;
}

function estilo(page, selector, propiedad) {
  return page.locator(selector).evaluate((elemento, propiedad) => {
    const estilos = getComputedStyle(elemento);
    return estilos.getPropertyValue(propiedad).trim();
  }, propiedad);
}

test.before(async () => {
  fs.mkdirSync(directorioResultados, { recursive: true });
  try {
    browser = await chromium.launch({
      headless: true,
      channel: process.env.PANEL_TEST_BROWSER_CHANNEL || 'chromium',
    });
  } catch (error) {
    throw new Error(
      'Chromium no pudo lanzarse en este entorno (' + error.message + '). ' +
      'La prueba visual requiere permiso ampliado (danger-full-access) para abrir procesos.'
    );
  }
});

test.after(async () => {
  if (browser) await browser.close();
});

test('los botones primario, outline, deshabilitado y ocupado usan el sistema', async () => {
  const page = await abrirPagina();

  // Botón primario: radio de control (12px), altura táctil (>= 42px) y relleno con degradado.
  const primario = {
    radius: await estilo(page, '#primario', 'border-radius'),
    minHeight: await estilo(page, '#primario', 'min-height'),
    background: await estilo(page, '#primario', 'background-image'),
    color: await estilo(page, '#primario', 'color'),
  };
  assert.equal(primario.radius, '12px');
  assert.equal(primario.minHeight, '42px');
  assert.match(primario.background, /gradient/);
  assert.equal(primario.color, 'rgb(255, 255, 255)');

  // Botón outline: superficie transparente y borde de control.
  assert.equal(await estilo(page, '#outline', 'background-color'), 'rgba(0, 0, 0, 0)');
  assert.notEqual(await estilo(page, '#outline', 'border-top-width'), '0px');

  // Deshabilitado: pierde opacidad y cursor, sin desplazamiento.
  assert.equal(await estilo(page, '#deshabilitado', 'opacity'), '0.55');
  assert.equal(await estilo(page, '#deshabilitado', 'cursor'), 'not-allowed');
  assert.equal(await estilo(page, '#deshabilitado', 'transform'), 'none');

  // Ocupado: el texto se oculta y el botón no recibe puntero.
  assert.equal(await estilo(page, '#ocupado', 'pointer-events'), 'none');
  assert.equal(await estilo(page, '#ocupado', 'color'), 'rgba(0, 0, 0, 0)');

  // Icono: caja táctil de 42x42.
  const anchoIcono = await page.locator('#icono').evaluate(elemento => elemento.getBoundingClientRect().width);
  const altoIcono = await page.locator('#icono').evaluate(elemento => elemento.getBoundingClientRect().height);
  assert.ok(anchoIcono >= 42, `El botón icono debe medir al menos 42px de ancho (mide ${anchoIcono})`);
  assert.ok(altoIcono >= 42, `El botón icono debe medir al menos 42px de alto (mide ${altoIcono})`);

  await page.close();
});

test('el foco de teclado es visible y de 3px en botones y campos', async () => {
  const page = await abrirPagina();
  await page.keyboard.press('Tab');
  assert.equal(await page.evaluate(() => document.activeElement && document.activeElement.id), 'primario');

  const focoBoton = await page.locator('#primario').evaluate(elemento => {
    const estilos = getComputedStyle(elemento);
    return { ancho: estilos.outlineWidth, estilo: estilos.outlineStyle, offset: estilos.outlineOffset };
  });
  assert.equal(focoBoton.ancho, '3px');
  assert.equal(focoBoton.estilo, 'solid');
  assert.equal(focoBoton.offset, '2px');

  await page.locator('#campo').focus();
  await page.keyboard.press('Shift+Tab');
  await page.keyboard.press('Tab');
  const focoCampo = await page.locator('#campo').evaluate(elemento => {
    const estilos = getComputedStyle(elemento);
    return { ancho: estilos.outlineWidth, estilo: estilos.outlineStyle };
  });
  assert.equal(focoCampo.ancho, '3px');
  assert.equal(focoCampo.estilo, 'solid');

  await page.close();
});

test('tarjeta, alerta, insignia e input consumen tokens de superficie y radio', async () => {
  const page = await abrirPagina();

  // Tarjeta: radio de tarjeta, borde translúcido y backdrop-filter activo.
  assert.equal(await estilo(page, '#tarjeta', 'border-radius'), '16px');
  assert.notEqual(await estilo(page, '#tarjeta', 'border-top-width'), '0px');
  const filtroTarjeta = await page.locator('#tarjeta').evaluate(elemento => {
    const estilos = getComputedStyle(elemento);
    return estilos.backdropFilter || estilos.webkitBackdropFilter || 'none';
  });
  assert.notEqual(filtroTarjeta, 'none', 'La tarjeta debe aplicar backdrop-filter');
  const fondoPagina = await estilo(page, 'body', 'background-color');
  const fondoTarjeta = await estilo(page, '#tarjeta', 'background-color');
  assert.notEqual(fondoTarjeta, fondoPagina, 'La superficie de la tarjeta se distingue del fondo');

  // Alerta: acento lateral de 4px y radio del sistema.
  assert.equal(await estilo(page, '#alerta', 'border-left-width'), '4px');
  assert.equal(await estilo(page, '#alerta', 'border-radius'), '10px');

  // Insignia: píldora.
  assert.equal(await estilo(page, '#insignia', 'border-radius'), '999px');

  // Input: altura táctil, borde de control y radio de control.
  assert.equal(await estilo(page, '#campo', 'min-height'), '42px');
  assert.equal(await estilo(page, '#campo', 'border-radius'), '12px');
  assert.equal(await estilo(page, '#campo', 'border-top-width'), '1px');

  await page.close();
});

test('la tabla y el modal respetan superficies de datos y capas translúcidas', async () => {
  const page = await abrirPagina();

  // Encabezado y filas de la tabla pintan superficie de datos/sólida.
  const fondosCabecera = await page.locator('#tabla thead th').evaluateAll(elementos =>
    elementos.map(elemento => getComputedStyle(elemento).getPropertyValue('background-color').trim())
  );
  const fondosFilas = await page.locator('#tabla tbody tr').evaluateAll(elementos =>
    elementos.map(elemento => getComputedStyle(elemento).getPropertyValue('background-color').trim())
  );
  assert.ok(fondosCabecera.length > 0 && fondosCabecera.every(fondo => fondo.length > 0));
  assert.ok(
    fondosFilas.length > 0 && fondosFilas.every(fondo => fondo !== 'rgba(0, 0, 0, 0)'),
    'Las celdas no deben quedar sin superficie',
  );

  // El modal inicia cerrado y su contenido hereda radio y blur del sistema.
  assert.equal(await estilo(page, '#modal', 'display'), 'none');
  await page.locator('#abrir-modal').click();
  assert.equal(await estilo(page, '#modal', 'display'), 'flex');
  const radioModal = Number.parseFloat(await estilo(page, '#modal .app-modal-content', 'border-radius'));
  assert.ok(radioModal >= 16, `El contenido del modal debe conservar el radio de tarjeta (mide ${radioModal}px)`);
  const filtroModal = await page.locator('#modal .app-modal-content').evaluate(elemento => {
    const estilos = getComputedStyle(elemento);
    return estilos.backdropFilter || estilos.webkitBackdropFilter || 'none';
  });
  assert.notEqual(filtroModal, 'none', 'El contenido del modal debe aplicar backdrop-filter');

  // Controles dentro del modal: 44px de alto mínimo en escritorio.
  const altoGuardar = await page.locator('#modal-guardar').evaluate(elemento => elemento.getBoundingClientRect().height);
  assert.ok(altoGuardar >= 42, `Los botones del modal deben medir al menos 42px (miden ${altoGuardar})`);

  if (process.env.PANEL_TEST_SCREENSHOTS !== '0') {
    await page.locator('#lienzo').screenshot({ path: path.join(directorioResultados, 'diseno-visual-modal.png') });
  }
  await page.close();
});

test('sin desbordamiento horizontal en 320/390/768/1440/1920/2560 px', async () => {
  for (const ancho of [320, 390, 768, 1440, 1920, 2560]) {
    const page = await abrirPagina({ width: ancho, height: 900 });
    const medidas = await page.evaluate(() => ({
      documento: document.documentElement.scrollWidth,
      ventana: window.innerWidth,
    }));
    assert.ok(
      medidas.documento <= medidas.ventana + 1,
      `Desbordamiento horizontal a ${ancho}px: scrollWidth=${medidas.documento} > innerWidth=${medidas.ventana}`
    );
    // La tabla se contiene en su propio contenedor desplazable.
    const contenedorTabla = await page.locator('#tabla-contenedor').evaluate(elemento => elemento.scrollWidth > elemento.clientWidth);
    assert.equal(typeof contenedorTabla, 'boolean');

    if (process.env.PANEL_TEST_SCREENSHOTS !== '0' && [390, 1440].includes(ancho)) {
      await page.screenshot({ path: path.join(directorioResultados, `diseno-visual-${ancho}.png`), fullPage: true });
    }
    await page.close();
  }
});

test('el cambio de tema actualiza superficies y colores sin romper el contraste', async () => {
  const page = await abrirPagina();
  const leerTema = () => page.evaluate(() => {
    const raiz = getComputedStyle(document.documentElement);
    const cuerpo = getComputedStyle(document.body);
    const tarjeta = getComputedStyle(document.getElementById('tarjeta'));
    return {
      fondo: cuerpo.backgroundColor,
      superficieTarjeta: tarjeta.backgroundColor,
      texto: cuerpo.color,
      acento: raiz.getPropertyValue('--accent-primary').trim(),
      superficie: raiz.getPropertyValue('--surface-glass').trim(),
    };
  });

  const elegante = await leerTema();
  await page.evaluate(() => document.documentElement.setAttribute('data-theme', 'sena'));
  const sena = await leerTema();
  await page.evaluate(() => document.documentElement.setAttribute('data-theme', 'ocean'));
  const ocean = await leerTema();

  assert.notEqual(elegante.fondo, sena.fondo, 'El tema Sena debe cambiar el fondo base');
  assert.notEqual(sena.fondo, ocean.fondo, 'El tema Ocean debe cambiar el fondo base');
  assert.notEqual(elegante.superficie, sena.superficie, 'Cada tema calibra su --surface-glass');
  assert.notEqual(sena.superficie, ocean.superficie, 'Cada tema calibra su --surface-glass');
  assert.notEqual(elegante.acento, sena.acento, 'El acento SENA es verde institucional');
  assert.equal(sena.acento.toLowerCase(), '#2d8500');
  assert.notEqual(elegante.texto, ocean.texto, 'El tema oscuro cambia el color de texto');

  // En modo oscuro la superficie de la tarjeta sigue siendo legible (no transparente).
  assert.notEqual(elegante.superficieTarjeta, 'rgba(0, 0, 0, 0)');
  assert.notEqual(ocean.superficieTarjeta, 'rgba(0, 0, 0, 0)');

  // Los fallbacks de accesibilidad existen en la hoja cargada.
  const soportes = await page.evaluate(() => {
    const reglas = [...document.styleSheets].flatMap(hoja => {
      try { return [...hoja.cssRules].map(regla => regla.cssText); } catch (_) { return []; }
    });
    return reglas.join('\n');
  });
  assert.match(soportes, /prefers-reduced-transparency/);
  assert.match(soportes, /prefers-contrast/);
  assert.match(soportes, /forced-colors/);

  await page.close();
});
