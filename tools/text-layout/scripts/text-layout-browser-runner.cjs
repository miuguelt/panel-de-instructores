const { spawn } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { INCLUDED_SCOPES, DEFAULT_VIEWPORTS, discoverIndexPages, resolveTemplateAssets } = require('./text-layout-browser-discovery.cjs');
const { createStressExpression, createAuditExpression } = require('./text-layout-browser-probes.cjs');
const { CDPClient, getJson, wait, resolveEdgePath, getFreePort, waitForTarget, waitForPage } = require('./text-layout-browser-engine.cjs');

async function runBrowserAudit(root, options = {}) {
  const absoluteRoot = path.resolve(root);
  const pages = discoverIndexPages(absoluteRoot, options.scopes || INCLUDED_SCOPES, options.allPages === true);
  const edgePath = resolveEdgePath(options.edgePath);
  if (pages.length && !edgePath) throw new Error('No se encontró Microsoft Edge. Define DEVBRAIN_EDGE_PATH para indicar su ruta.');
  if (!pages.length) return { pagesScanned: 0, viewportsChecked: 0, findings: [], pages: [] };

  const port = await getFreePort();
  const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'devbrain-text-layout-'));
  const browser = spawn(edgePath, [
    `--remote-debugging-port=${port}`,
    '--headless=new',
    '--disable-gpu',
    '--no-first-run',
    '--no-default-browser-check',
    `--user-data-dir=${userDataDir}`,
    '--disable-background-networking',
    '--disable-sync',
    '--disable-component-update',
    '--disable-default-apps',
    '--allow-file-access-from-files',
    '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1',
    'about:blank'
  ], { stdio: 'ignore', windowsHide: true });
  let cdp = null;
  const findings = [];
  const pageResults = [];
  const viewports = options.viewports || DEFAULT_VIEWPORTS;

  try {
    const version = await waitForTarget(port, options.startupAttempts || 40);
    const tabs = await getJson(`http://127.0.0.1:${port}/json/list`);
    const tab = tabs.find(item => item.type === 'page');
    if (!tab || !tab.webSocketDebuggerUrl) throw new Error('Microsoft Edge no publicó una pestaña para auditar.');
    cdp = new CDPClient(tab.webSocketDebuggerUrl);
    await cdp.send('Page.enable');
    await cdp.send('Runtime.enable');
    await cdp.send('Network.enable');
    await cdp.send('Network.setBlockedURLs', { urls: ['http://*', 'https://*'] });

    for (let pageIndex = 0; pageIndex < pages.length; pageIndex += 1) {
      const page = pages[pageIndex];
      const relativePage = path.relative(absoluteRoot, page).replace(/\\/g, '/');
      await cdp.send('Page.navigate', { url: pathToFileURL(page).href });
      await waitForPage(cdp);
      const templateAssets = resolveTemplateAssets(page, absoluteRoot);
      if (templateAssets.styles.length || templateAssets.scripts.length) {
        const styles = JSON.stringify(templateAssets.styles.map(item => item.content));
        const scripts = JSON.stringify(templateAssets.scripts.map(item => item.content));
        await cdp.evaluate(`(() => {
          for (const content of ${styles}) {
            const style = document.createElement('style');
            style.setAttribute('data-devbrain-prose-audit', '');
            style.textContent = content;
            document.head.append(style);
          }
          for (const content of ${scripts}) {
            const script = document.createElement('script');
            script.setAttribute('data-devbrain-prose-runtime', '');
            script.textContent = content;
            document.head.append(script);
          }
          return true;
        })()`);
      }
      await cdp.evaluate(createStressExpression(options.stressRepeats));
      const pageResult = { page: relativePage, viewports: [] };
      for (const viewport of viewports) {
        await cdp.send('Emulation.setDeviceMetricsOverride', {
          width: viewport.width,
          height: 900,
          deviceScaleFactor: 1,
          mobile: viewport.width < 640
        });
        // A 200 % desktop zoom is represented by the halved 720 CSS px viewport above.
        // Applying a pinch scale here would shift the visual viewport and double-count zoom.
        await cdp.send('Emulation.setPageScaleFactor', { pageScaleFactor: 1 });
        await cdp.evaluate('window.scrollTo(0, 0)');
        await wait(options.renderDelayMs ?? 200);
        const result = await cdp.evaluate(createAuditExpression(options.probeSelectors || []));
        pageResult.viewports.push({
          label: viewport.label,
          viewportWidth: result.viewportWidth,
          pageWidth: result.pageWidth,
          naturalTextBlocks: result.naturalTextBlocks,
          probes: result.probes
        });
        for (const finding of result.findings) {
          findings.push({ page: relativePage, viewport: viewport.label, ...finding });
        }
      }
      pageResults.push(pageResult);
      if (options.progress === true && (pageIndex === 0 || (pageIndex + 1) % 10 === 0 || pageIndex === pages.length - 1)) {
        console.log(`Páginas revisadas: ${pageIndex + 1}/${pages.length}.`);
      }
    }

    return {
      browser: version.Browser,
      temporaryProfile: userDataDir,
      profileCleanup: 'pendiente: perfil conservado',
      pagesScanned: pageResults.length,
      viewportsChecked: pageResults.reduce((total, page) => total + page.viewports.length, 0),
      findings,
      pages: pageResults
    };
  } finally {
    if (cdp) {
      await cdp.send('Browser.close');
      cdp.close();
    }
    if (browser.exitCode === null) browser.kill();
    await wait(500);

  }
}

module.exports = { runBrowserAudit };
