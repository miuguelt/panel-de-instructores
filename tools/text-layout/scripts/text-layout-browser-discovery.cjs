const fs = require('node:fs');
const path = require('node:path');

const INCLUDED_SCOPES = ['_projects', '_library', '_infrastructure', '_core', '_docs', 'docs', 'Configuracion'];
const GENERATED_DIRECTORIES = new Set([
  '.git', '.agents', '.cache', '.codex', '.cursor', '.next', '.opencode', '.pytest_cache', '.ruff_cache',
  '.venv', '.vscode', '.windsurf', '__pycache__', 'archive', '_archive', '_backups', '_to_delete', 'artifacts',
  'backups', 'build', 'coverage', 'dist', 'generated', 'htmlcov', 'logs', 'node_modules', 'output',
  'outputs', 'playwright-report', 'target', 'test-results', 'tmp', 'vendor', 'venv', 'venv_linux', 'venv_win'
]);
const DEFAULT_VIEWPORTS = [
  { label: '320px', width: 320 },
  { label: '390px', width: 390 },
  { label: '768px', width: 768 },
  { label: '1440px', width: 1440 },
  { label: '1920px', width: 1920 },
  { label: '2560px', width: 2560 },
  { label: '200% zoom (720 CSS px)', width: 720, zoom: 200 }
];

function findVitePackageRoot(filePath, workspaceRoot) {
  let directory = path.dirname(filePath);
  while (directory === workspaceRoot || directory.startsWith(workspaceRoot + path.sep)) {
    const manifestPath = path.join(directory, 'package.json');
    if (fs.existsSync(manifestPath)) {
      try {
        const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
        const dependencies = { ...manifest.dependencies, ...manifest.devDependencies, ...manifest.peerDependencies };
        if (Object.hasOwn(dependencies, 'vite')) return directory;
      } catch {
        // A malformed nested manifest does not hide a valid workspace-level manifest.
      }
    }
    if (directory === workspaceRoot) break;
    directory = path.dirname(directory);
  }
  return null;
}

function hasLoadableStylesheet(filePath, source) {
  for (const tag of source.matchAll(/<link\b[^>]*>/gi)) {
    const markup = tag[0];
    if (!/\brel\s*=\s*(["'])stylesheet\1/i.test(markup)) continue;
    const href = markup.match(/\bhref\s*=\s*(["'])(.*?)\1/i)?.[2];
    if (!href || /^(?:[a-z]+:|\/|#|data:)/i.test(href)) continue;
    const localPath = path.resolve(path.dirname(filePath), href.split(/[?#]/, 1)[0]);
    if (fs.existsSync(localPath) && fs.statSync(localPath).isFile()) return true;
  }
  return false;
}

function isServerTemplate(filePath, workspaceRoot) {
  const source = fs.readFileSync(filePath, 'utf8');
  if (/{%\s*(?:extends|block|include|macro|endblock)\b/.test(source)) return true;
  if (!/<script\b(?=[^>]*\btype\s*=\s*(?:"module"|'module'))(?=[^>]*\bsrc\s*=)[^>]*>/i.test(source)) return false;
  const vitePackageRoot = findVitePackageRoot(filePath, workspaceRoot);
  return Boolean(vitePackageRoot && !hasLoadableStylesheet(filePath, source));
}

function discoverIndexPages(root, scopes = INCLUDED_SCOPES, includeStandalone = false) {
  const absoluteRoot = path.resolve(root);
  const pages = [];
  const visit = directory => {
    const entries = fs.readdirSync(directory, { withFileTypes: true });
    for (const entry of entries) {
      const entryPath = path.join(directory, entry.name);
      if (entry.isDirectory()) {
        if (!entry.name.startsWith('.') && !GENERATED_DIRECTORIES.has(entry.name.toLowerCase())) visit(entryPath);
      } else if (entry.isFile() && /\.html?$/i.test(entry.name) && !isServerTemplate(entryPath, absoluteRoot) && (entry.name.toLowerCase() === 'index.html' || includeStandalone && /<!doctype\s+html|<html\b/i.test(fs.readFileSync(entryPath, 'utf8')))) {
        pages.push(entryPath);
      }
    }
  };

  for (const scope of scopes) {
    const scopePath = path.join(absoluteRoot, scope);
    if (fs.existsSync(scopePath) && fs.statSync(scopePath).isDirectory()) visit(scopePath);
  }
  return pages.sort((left, right) => left.localeCompare(right));
}

function resolveTemplateAssets(filePath, workspaceRoot) {
  const source = fs.readFileSync(filePath, 'utf8');
  const root = path.resolve(workspaceRoot);
  const styles = [];
  const scripts = [];
  const assetFromPath = candidate => {
    const absolute = path.resolve(candidate);
    if (!absolute.startsWith(root + path.sep) || !fs.existsSync(absolute) || !fs.statSync(absolute).isFile()) return null;
    return { path: absolute, content: fs.readFileSync(absolute, 'utf8') };
  };
  const vitePublicAsset = reference => {
    let directory = path.dirname(path.resolve(filePath));
    while (directory === root || directory.startsWith(root + path.sep)) {
      const packageFile = path.join(directory, 'package.json');
      if (fs.existsSync(packageFile)) {
        try {
          const manifest = JSON.parse(fs.readFileSync(packageFile, 'utf8'));
          const dependencies = { ...manifest.dependencies, ...manifest.devDependencies, ...manifest.peerDependencies };
          if (Object.hasOwn(dependencies, 'vite')) {
            const asset = assetFromPath(path.join(directory, 'public', reference.replace(/^[/\\]+/, '')));
            if (asset) return asset;
          }
        } catch {
          return null;
        }
      }
      if (directory === root) break;
      directory = path.dirname(directory);
    }
    return null;
  };
  const tags = source.matchAll(/<(link|script)\b[^>]*>/gi);
  for (const match of tags) {
    const tag = match[1].toLowerCase();
    const markup = match[0];
    const marker = tag === 'link' ? /\bdata-devbrain-prose(?:\s|=|\/|>)/i : /\bdata-devbrain-prose-runtime(?:\s|=|\/|>)/i;
    if (!marker.test(markup)) continue;
    const attribute = tag === 'link' ? /\bhref\s*=\s*(["'])(.*?)\1/i : /\bsrc\s*=\s*(["'])(.*?)\1/i;
    const reference = markup.match(attribute)?.[2] || '';
    const flask = reference.match(/url_for\(\s*["']static["']\s*,\s*filename\s*=\s*["']([^"']+)["']\s*\)/i);
    const django = reference.match(/{%\s*static\s+["']([^"']+)["']\s*%}/i);
    const assetPath = flask?.[1] || django?.[1];
    let resolved = null;
    if (assetPath) {
      let directory = path.dirname(path.resolve(filePath));
      while (directory === root || directory.startsWith(root + path.sep)) {
        const asset = assetFromPath(path.resolve(directory, 'static', assetPath));
        if (asset) {
          resolved = asset;
          break;
        }
        if (directory === root) break;
        directory = path.dirname(directory);
      }
    } else {
      const cleanReference = reference.split(/[?#]/, 1)[0];
      if (!cleanReference) continue;
      if (cleanReference.startsWith('/')) {
        resolved = vitePublicAsset(cleanReference);
        if (!resolved) resolved = assetFromPath(path.resolve(root, cleanReference.replace(/^[/\\]+/, '')));
      } else {
        resolved = assetFromPath(path.resolve(path.dirname(filePath), cleanReference));
        if (!resolved) resolved = vitePublicAsset(cleanReference);
      }
    }
    if (!resolved) continue;
    if (tag === 'link') styles.push(resolved);
    else scripts.push(resolved);
  }
  return { styles, scripts };
}

module.exports = { INCLUDED_SCOPES, GENERATED_DIRECTORIES, DEFAULT_VIEWPORTS, discoverIndexPages, resolveTemplateAssets };
