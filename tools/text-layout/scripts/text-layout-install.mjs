import { existsSync, mkdirSync, readFileSync, writeFileSync, copyFileSync, readdirSync } from 'node:fs';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const source = dirname(fileURLToPath(import.meta.url));
const types = ['static','python','node','fullstack','wails','powershell'];
const excludedDirectories = new Set(['.git','.cache','.next','.pytest_cache','.venv','__pycache__','backups','build','coverage','dist','generated','htmlcov','node_modules','output','outputs','playwright-report','target','test-results','vendor','venv','venv_linux','venv_win','_archive','_backups','_to_delete']);

function copyAsset(origin, destination) {
  mkdirSync(dirname(destination),{recursive:true});
  if (resolve(origin) !== resolve(destination)) copyFileSync(origin,destination);
}

function ensureDocumentHead(html) {
  if (/<head\b[^>]*>/i.test(html)) return html;
  const opening = html.match(/<html\b[^>]*>/i);
  if (!opening) return html;
  const start = opening.index + opening[0].length;
  const remainder = html.slice(start);
  const firstBodyContent = /<(?:body|main|header|nav|section|article|aside|div|p|h[1-6]|ul|ol|form|footer|table|figure|svg|button|details|pre)\b/i.exec(remainder);
  const closing = firstBodyContent ? start + firstBodyContent.index : html.search(/<\/html\s*>/i);
  const end = closing < 0 ? html.length : closing;
  return `${html.slice(0,start)}\n<head>\n${html.slice(start,end)}\n</head>\n${html.slice(end)}`;
}

export function connectEntry(project, entry) {
  const file = join(project,...entry.split('/'));
  let html = ensureDocumentHead(readFileSync(file,'utf8'));
  const entryParts = entry.split('/');
  const templateIndex = entryParts.lastIndexOf('templates');
  const template = templateIndex >= 0;
  const templateBase = template ? entryParts.slice(0,templateIndex).join('/') : '';
  const vitePackageRoot = template ? null : findVitePackageRoot(project, entry);
  const css = template
    ? join(project,...templateBase.split('/'),'static/css/devbrain-prose.css')
    : vitePackageRoot
      ? join(vitePackageRoot,'public/devbrain-prose.css')
      : join(dirname(file),'devbrain-prose.css');
  copyAsset(join(source,'../templates/prose-layout.css'),css);
  const runtime = vitePackageRoot ? join(vitePackageRoot,'public/devbrain-prose.js') : css.replace(/\.css$/,'.js');
  copyAsset(join(source,'../templates/prose-layout.js'),runtime);
  const djangoStatic = template && /{\%\s*(?:load\s+static|static\b)/.test(html);
  const scriptHref = template
    ? djangoStatic ? "{% static 'css/devbrain-prose.js' %}" : "{{ url_for('static', filename='css/devbrain-prose.js') }}"
    : vitePackageRoot ? '/devbrain-prose.js' : relative(dirname(file),runtime).replaceAll('\\','/');
  const href = template
    ? djangoStatic ? "{% static 'css/devbrain-prose.css' %}" : "{{ url_for('static', filename='css/devbrain-prose.css') }}"
    : vitePackageRoot ? '/devbrain-prose.css' : relative(dirname(file),css).replaceAll('\\','/');
  if (djangoStatic && !/{%\s*load\s+static\s*%}/.test(html)) html = html.replace(/({%\s*extends\b[^%]*%}\s*)/i,'$1{% load static %}\n');
  if (!html.includes('data-devbrain-prose')) html = html.replace(/<\/head>/i,`<link rel="stylesheet" href="${href}" data-devbrain-prose>\n</head>`);
  if (!html.includes('data-devbrain-prose-runtime')) html = html.replace(/<\/head>/i,`<script defer src="${scriptHref}" data-devbrain-prose-runtime></script>\n</head>`);
  writeFileSync(file,html,'utf8');
}

function findVitePackageRoot(project, entry) {
  const root = resolve(project);
  let directory = resolve(root,...dirname(entry).split('/'));
  while (directory === root || directory.startsWith(`${root}${process.platform === 'win32' ? '\\' : '/'}`)) {
    const packageFile = join(directory,'package.json');
    if (existsSync(packageFile)) {
      try {
        const manifest = JSON.parse(readFileSync(packageFile,'utf8'));
        const dependencies = {...manifest.dependencies,...manifest.devDependencies,...manifest.peerDependencies};
        if (Object.hasOwn(dependencies,'vite')) return directory;
      } catch {
        return null;
      }
    }
    if (directory === root) break;
    directory = dirname(directory);
  }
  return null;
}

export function discoverPageEntries(project) {
  const pages = [];
  const pending = [resolve(project)];
  while (pending.length) {
    const directory = pending.pop();
    for (const entry of readdirSync(directory,{withFileTypes:true})) {
      if (entry.isSymbolicLink()) continue;
      const file = join(directory,entry.name);
      if (entry.isDirectory()) {
        if (!entry.name.startsWith('.') && !excludedDirectories.has(entry.name.toLowerCase())) pending.push(file);
        continue;
      }
      if (!entry.isFile() || !/\.html?$/i.test(entry.name)) continue;
      const html = readFileSync(file,'utf8');
      const relativePath = relative(project,file).replaceAll('\\','/');
      const template = relativePath.split('/').includes('templates');
      const fullDocument = /<!doctype\s+html|<html\b/i.test(html);
      const hasHead = /<head\b[\s>]/i.test(html) && /<\/head\s*>/i.test(html);
      if (fullDocument || template && hasHead) pages.push(relativePath);
    }
  }
  return pages.sort((left,right)=>left.localeCompare(right));
}

export function discoverNextLayouts(project) {
  const root = resolve(project);
  const layouts = [];
  const pending = [root];
  while (pending.length) {
    const directory = pending.pop();
    for (const entry of readdirSync(directory,{withFileTypes:true})) {
      if (entry.isSymbolicLink()) continue;
      const file = join(directory,entry.name);
      if (entry.isDirectory()) {
        if (!entry.name.startsWith('.') && !excludedDirectories.has(entry.name.toLowerCase())) pending.push(file);
        continue;
      }
      if (!entry.isFile() || !/^layout\.(?:js|jsx|ts|tsx)$/i.test(entry.name) || !['app','src\\app','src/app'].includes(relative(root,directory).replaceAll('\\','/'))) continue;
      const appRoot = directory;
      let packageRoot = dirname(appRoot);
      let manifest;
      while (packageRoot !== dirname(packageRoot) && (packageRoot === root || packageRoot.startsWith(`${root}${process.platform === 'win32' ? '\\' : '/'}`))) {
        const packageFile = join(packageRoot,'package.json');
        if (existsSync(packageFile)) {
          try { manifest = JSON.parse(readFileSync(packageFile,'utf8')); }
          catch { manifest = undefined; }
          break;
        }
        packageRoot = dirname(packageRoot);
      }
      const dependencies = {...manifest?.dependencies,...manifest?.devDependencies,...manifest?.peerDependencies};
      if (!Object.hasOwn(dependencies,'next')) continue;
      layouts.push({layout:relative(root,file).replaceAll('\\','/'),appRoot:relative(root,appRoot).replaceAll('\\','/'),packageRoot:relative(root,packageRoot).replaceAll('\\','/') || '.'});
    }
  }
  return layouts.sort((left,right)=>left.layout.localeCompare(right.layout));
}

export function connectNextLayout(project, nextLayout) {
  const layout = join(project,...nextLayout.layout.split('/'));
  const appRoot = join(project,...nextLayout.appRoot.split('/'));
  const packageRoot = nextLayout.packageRoot === '.' ? project : join(project,...nextLayout.packageRoot.split('/'));
  const css = join(appRoot,'devbrain-prose.css');
  const runtime = join(packageRoot,'public/devbrain-prose.js');
  copyAsset(join(source,'../templates/prose-layout.css'),css);
  copyAsset(join(source,'../templates/prose-layout.js'),runtime);
  let code = readFileSync(layout,'utf8');
  const scriptImport = code.match(/import\s+([A-Za-z_$][\w$]*)\s+from\s+['"]next\/script['"]/);
  const scriptName = scriptImport?.[1] || 'Script';
  const imports = [];
  if (!scriptImport) imports.push("import Script from 'next/script';");
  if (!code.includes('devbrain-prose.css')) imports.push("import './devbrain-prose.css';");
  if (imports.length) {
    const directives = code.match(/^(?:\s*['"]use (?:client|server|strict)['"];?\s*)+/);
    const offset = directives?.[0].length || 0;
    code = `${code.slice(0,offset)}${imports.join('\n')}\n${code.slice(offset)}`;
  }
  if (!code.includes('data-devbrain-prose-runtime')) {
    if (!/<\/body\s*>/i.test(code)) throw new Error(`El layout de Next.js no contiene </body>: ${nextLayout.layout}`);
    code = code.replace(/([ \t]*)<\/body\s*>/i,(_,indent)=>`${indent}  <${scriptName} src="/devbrain-prose.js" strategy="afterInteractive" data-devbrain-prose-runtime />\n${indent}</body>`);
  }
  writeFileSync(layout,code,'utf8');
}

export function discoverManagedFiles(project) {
  const root = resolve(project);
  const files = new Set();
  for (const entry of discoverPageEntries(root)) {
    files.add(entry);
    const entryParts = entry.split('/');
    const templateIndex = entryParts.lastIndexOf('templates');
    const templateBase = templateIndex >= 0 ? entryParts.slice(0,templateIndex).join('/') : '';
    const vitePackageRoot = templateIndex >= 0 ? null : findVitePackageRoot(root, entry);
    const css = templateIndex >= 0
      ? join(templateBase,'static/css/devbrain-prose.css')
      : vitePackageRoot
        ? join(relative(root,vitePackageRoot),'public/devbrain-prose.css')
        : join(dirname(entry),'devbrain-prose.css');
    const runtime = vitePackageRoot
      ? join(relative(root,vitePackageRoot),'public/devbrain-prose.js')
      : css.replace(/\.css$/,'.js');
    files.add(css.replaceAll('\\','/'));
    files.add(runtime.replaceAll('\\','/'));
  }
  const nextLayouts = discoverNextLayouts(root);
  for (const item of nextLayouts) {
    files.add(item.layout);
    files.add(join(item.appRoot,'devbrain-prose.css').replaceAll('\\','/'));
    files.add(join(item.packageRoot,'public/devbrain-prose.js').replaceAll('\\','/'));
  }
  return {entries:discoverPageEntries(root),nextLayouts,files:[...files].sort()};
}

export function installProject(project, type = 'static', createEntry = true) {
  if (!types.includes(type)) throw new Error('Tipo de proyecto no admitido.');
  const nextLayouts = discoverNextLayouts(project);
  let entries = discoverPageEntries(project);
  if (type === 'powershell' && !entries.length && !nextLayouts.length) return {project,applicable:false,reason:'Sin superficie de lectura.',entries:[]};
  const tools = join(project,'tools/text-layout');
  for (const asset of ['text-layout-audit.mjs','text-layout-browser-audit.cjs','text-layout-browser-discovery.cjs','text-layout-browser-probes.cjs','text-layout-browser-engine.cjs','text-layout-browser-runner.cjs','text-layout-migration.mjs','tests/text-layout-audit.test.mjs','tests/text-layout-browser-engine.test.cjs','tests/prose-layout.test.mjs','tests/prose-runtime.test.cjs','text-layout-install.mjs','tests/text-layout-install.test.mjs']) {
    copyAsset(join(source,asset),join(tools,'scripts',asset));
  }
  for (const name of ['prose-layout.css','prose-layout.js','text-layout-workflow.yml']) copyAsset(join(source,'../templates',name),join(tools,'templates',name));
  const workflow = join(project,'.github/workflows/text-layout.yml');
  const workflowTarget = existsSync(workflow) && !readFileSync(workflow,'utf8').startsWith('# DevBrain:') ? join(project,'.github/workflows/devbrain-text-layout.yml') : workflow;
  copyAsset(join(source,'../templates/text-layout-workflow.yml'),workflowTarget);
  if (!entries.length && !nextLayouts.length && createEntry) {
    const entry = type === 'python' ? 'app/interfaces/http/templates/base.html' : type === 'fullstack' || type === 'wails' ? 'frontend/index.html' : 'index.html';
    const file = join(project,entry);
    mkdirSync(dirname(file),{recursive:true});
    writeFileSync(file,'<!doctype html>\n<html lang="es-CO"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Proyecto</title></head><body><main></main></body></html>\n','utf8');
    entries = [entry];
  }
  for (const entry of entries) connectEntry(project,entry);
  for (const layout of nextLayouts) connectNextLayout(project,layout);
  const applicable = entries.length > 0 || nextLayouts.length > 0;
  return {project,applicable,entries,nextLayouts:nextLayouts.map(item=>item.layout),status:applicable ? 'conectado: falta validación visual' : 'pendiente: declarar la entrada de la interfaz'};
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const project = process.argv[2];
  if (!project) throw new Error('Indique la ruta del proyecto.');
  if (process.argv.includes('--discover-managed-json')) {
    console.log(JSON.stringify(discoverManagedFiles(resolve(project))));
    process.exit(0);
  }
  console.log(JSON.stringify(installProject(resolve(project),process.argv[3] || 'static',!process.argv.includes('--existing'))));
}
