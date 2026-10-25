import { existsSync, readdirSync, readFileSync, writeFileSync, mkdirSync, copyFileSync } from 'node:fs';
import { dirname, extname, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { extractCssRules, isNaturalTextSelector } from './text-layout-audit.mjs';

const roots = ['_projects', '_library', '_infrastructure', '_core/skills', '_docs', 'docs', 'Configuracion'];
const excluded = new Set(['node_modules', 'vendor', '.git', 'dist', 'build', 'coverage', 'htmlcov', 'artifacts', 'test-results', 'playwright-report', 'target', '.next', '.cache', '.venv', 'venv', 'venv_win', 'venv_linux', '__pycache__', '_archive', '_backups', 'backups', 'vault', 'legacy', '_graveyard', '_to_delete', 'generated', 'output', 'outputs']);
const contract = readFileSync(new URL('../templates/prose-layout.css', import.meta.url), 'utf8').trim();
const marker = '/* devbrain-prose-contract:start */';

function isGeneratedHashedCss(filePath) {
  return /(?:^|[\\/])assets[\\/](?:index-)?[A-Za-z0-9_-]{8,}\.css$/i.test(filePath);
}

export function isProse(selector) {
  if (!isNaturalTextSelector(selector)) return false;
  if (/::|(?:^|[\s,>])(?:h[1-6]|button|input|textarea|select)(?:\b|$)/i.test(selector)) return false;
  return /(?:\bp\b|\bdd\b|\bli\b|\bblockquote\b|\bfigcaption\b|description|explanation|intro|prose|text-column|copy|lead|subtitle|timeline|lesson)/i.test(selector);
}

function isReadingRegion(selector) {
  if (/::|(?:^|[\s,>])(?:h[1-6]|button|input|textarea|select|pre|code|table|nav)(?:\b|$)/i.test(selector)) return false;
  if (/(?:^|[.#\s>])(?:code|toast|notification|alert|search|progress|button|btn|form|input|control|filter|image|icon|avatar|badge|chip|tag)[\w-]*/i.test(selector)) return false;
  return isProse(selector) || /(?:^|[.#\s>+~,(])(?:main|article|section|aside|[\w-]*(?:container|content|reading|timeline|explanation|lesson|layout|column|copy|prose|text|paragraph|story|guide|page|shell|wrapper)[\w-]*)(?=$|[.#\s:[>+~])/i.test(selector);
}

function migrateCssSegment(source) {
  const changes = [];
  let hasProse = false;
  for (const rule of extractCssRules(source)) {
    const prose = isProse(rule.selector);
    const region = isReadingRegion(rule.selector);
    if (!prose && !region) continue;
    hasProse = true;
    const body = source.slice(rule.bodyStart, rule.bodyEnd);
    let updated = body
      .replace(/((?:max-width|max-inline-size)\s*:)\s*(?:min\([^)]*(?:ch|px|r?em|vw)[^)]*\)|[\d.]+(?:ch|px|r?em|vw))(?=\s*[;}!]|\s*$)/gi, '$1100%')
      .replace(/(text-align\s*:)\s*(?:start|left|justify|initial|inherit)(?=\s*[;}]|\s*$)/gi, '$1var(--text-align-reading, start)')
      .replace(/((?:-webkit-)?hyphens\s*:)\s*(?:auto|var\(--hyphens-reading,\s*auto\))(?=\s*[;}]|\s*$)/gi, '$1none');
    if (prose) {
      updated = updated.replace(/((?:width|inline-size)\s*:)\s*(?:min\([^)]*(?:ch|px|r?em|vw)[^)]*\)|[\d.]+(?:ch|px|r?em|vw))(?=\s*[;}]|\s*$)/gi, '$1100%');
    }
    if (region) {
      updated = updated.replace(/(grid-template-columns\s*:[^;{}]*?)minmax\(\s*0\s*,\s*[\d.]+ch\s*\)/gi, '$1minmax(0,1fr)');
    }
    if (updated !== body) changes.push({ start:rule.bodyStart, end:rule.bodyEnd, text:updated });
  }
  for (const change of changes.sort((a,b)=>b.start-a.start)) source = source.slice(0,change.start)+change.text+source.slice(change.end);
  return { source, hasProse };
}

export function migrateCss(source) {
  const markerAt = source.indexOf(marker);
  if (markerAt >= 0) {
    const endMarker = '/* devbrain-prose-contract:end */';
    const endAt = source.indexOf(endMarker, markerAt);
    if (endAt < 0) return source;
    const before = migrateCssSegment(source.slice(0, markerAt).trimEnd());
    const after = migrateCssSegment(source.slice(endAt + endMarker.length));
    if (!before.hasProse && !after.hasProse) return source;
    return before.source.trimEnd() + '\n\n' + marker + '\n' + contract + '\n/* devbrain-prose-contract:end */' + after.source;
  }

  const migrated = migrateCssSegment(source);
  if (!migrated.hasProse) return source;
  return migrated.source.trimEnd() + '\n\n' + marker + '\n' + contract + '\n/* devbrain-prose-contract:end */\n';
}

export function classifySurface(category, source) {
  if (category === 'docx' || category === 'pdf') return 'renderizador';
  if (category === 'md') return 'documentación';
  if (['html', 'htm'].includes(category) && /{%|{{/.test(source)) return 'servidor';
  if (['html', 'htm'].includes(category) && /<script\b(?=[^>]*\btype\s*=\s*(?:"module"|'module'))(?=[^>]*\bsrc\s*=)[^>]*>/i.test(source)) return 'aplicación';
  if (['css', 'html', 'htm'].includes(category)) return 'estático';
  return 'aplicación';
}

export function inventory(root) {
  const rows = [];
  for (const scope of roots) {
    const start = resolve(root, scope);
    if (!existsSync(start)) continue;
    const pending = [start];
    while (pending.length) {
      for (const entry of readdirSync(pending.pop(), {withFileTypes:true})) {
        const full = resolve(entry.parentPath, entry.name);
        if (entry.isSymbolicLink()) continue;
        if (entry.isDirectory()) {
          if (!entry.name.startsWith('.') && !excluded.has(entry.name.toLowerCase())) pending.push(full);
          continue;
        }
        const extension = extname(full).toLowerCase();
        if (!['.html','.htm','.css','.scss','.vue','.svelte','.astro','.jsx','.tsx','.docx','.pdf','.md'].includes(extension)) continue;
        const path = relative(root,full).replaceAll('\\','/');
        if (/\.min\.(css|js)$|(?:^|\/)assets\/(lib|vendor)\/|^_infrastructure\/superpowers\//i.test(path) || isGeneratedHashedCss(path)) continue;
        const source = ['.docx', '.pdf'].includes(extension) ? '' : readFileSync(full, 'utf8');
        const method = classifySurface(extension.slice(1), source);
        rows.push({path, project:path.split('/').slice(0,2).join('/'), category:extension.slice(1), method, status:'pendiente'});
      }
    }
  }
  return rows.sort((a,b)=>a.path.localeCompare(b.path));
}

export function migrateFile(file, apply = false) {
  const source = readFileSync(file,'utf8');
  const updated = extname(file).toLowerCase() === '.css' ? migrateCss(source) : migrateHtml(source);
  if (updated === source) return false;
  if (apply) writeFileSync(file,updated,'utf8');
  return true;
}

function migrateHtmlSegment(source) {
  return source
    .replace(/(<style\b[^>]*>)([\s\S]*?)(<\/style\s*>)/gi, (_,open,css,close)=>open+migrateCss(css)+close)
    .replace(/(<(?:p|dd|blockquote)\b[^>]*\bstyle\s*=\s*)(["'])(.*?)\2/gi, (_,prefix,quote,css) => {
      const migratedCss = migrateCss(`p{${css}}`);
      const rule = extractCssRules(migratedCss)[0];
      return prefix+quote+migratedCss.slice(rule.bodyStart,rule.bodyEnd)+quote;
    });
}

function migrateHtml(source) {
  const hasLinkedContract = /<link\b(?=[^>]*\bdata-devbrain-prose(?:\s|=|\/|>))[^>]*>/i.test(source);
  return source.split(/(<noscript\b[^>]*>[\s\S]*?<\/noscript\s*>)/gi)
    .map((segment,index)=>hasLinkedContract && index % 2 === 1 ? segment : migrateHtmlSegment(segment))
    .join('');
}

export function runMigration(root, apply = false) {
  const rows = inventory(root);
  const changed = [];
  for (const row of rows) {
    if (!['css','html','htm'].includes(row.category) || row.path.endsWith('/templates/prose-layout.css') || row.path.toLowerCase().endsWith('/devbrain-prose.css')) continue;
    const file = resolve(root,row.path);
    if (!migrateFile(file,false)) continue;
    if (apply) {
      const backup = resolve(root,'output/text-layout/originals',row.path);
      if (!existsSync(backup)) { mkdirSync(dirname(backup),{recursive:true}); copyFileSync(file,backup); }
      migrateFile(file,true);
    }
    changed.push(row.path);
  }
  return { root:resolve(root), applied:apply, changed, surfaces:rows, status:'incompleto: falta verificación visual por superficie' };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const report = runMigration(process.cwd(),process.argv.includes('--apply'));
  const outputIndex = process.argv.indexOf('--report');
  if (outputIndex >= 0 && process.argv[outputIndex+1]) writeFileSync(process.argv[outputIndex+1],JSON.stringify(report,null,2),'utf8');
  console.log(JSON.stringify({changed:report.changed.length,surfaces:report.surfaces.length,status:report.status}));
}
