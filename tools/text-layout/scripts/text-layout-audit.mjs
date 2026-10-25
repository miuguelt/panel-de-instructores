import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { extname, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const SOURCE_ROOTS = ['_projects', '_library', '_infrastructure', '_core/skills', '_docs', 'docs', 'Configuracion'];
const STYLE_EXTENSIONS = new Set(['.css', '.scss', '.sass', '.less', '.html', '.htm', '.vue', '.svelte', '.astro', '.jsx', '.tsx']);
const SKIP_DIRECTORIES = new Set(['.git', '.agents', 'node_modules', 'vendor', 'dist', 'build', 'coverage', 'htmlcov', 'artifacts', 'test-results', 'playwright-report', 'target', '.next', '.cache', '.turbo', '.pytest_cache', '.venv', 'venv', 'venv_win', 'venv_linux', '__pycache__', 'archive', '_archive', '_backups', 'backups', '_to_delete', 'generated', 'output', 'outputs']);

export function stripComments(source) {
  return source.replace(/\/\*[\s\S]*?\*\//g, comment => comment.replace(/[^\r\n]/g, ' '));
}

function splitTopLevel(source, delimiter) {
  const parts = [];
  let start = 0, quote = '', escaped = false, depth = 0;
  for (let index = 0; index < source.length; index++) {
    const char = source[index];
    if (quote) {
      if (escaped) escaped = false;
      else if (char === '\\') escaped = true;
      else if (char === quote) quote = '';
    } else if (char === '"' || char === "'") quote = char;
    else if (char === '(' || char === '[' || char === '{') depth++;
    else if (char === ')' || char === ']' || char === '}') depth = Math.max(0, depth - 1);
    else if (char === delimiter && depth === 0) { parts.push(source.slice(start, index)); start = index + 1; }
  }
  parts.push(source.slice(start));
  return parts;
}

export function parseCssDeclarations(source) {
  const declarations = {};
  for (const item of splitTopLevel(source, ';')) {
    const pair = splitTopLevel(item, ':');
    if (pair.length < 2) continue;
    const property = pair.shift().trim().toLowerCase();
    if (property) declarations[property] = pair.join(':').trim().toLowerCase();
  }
  return declarations;
}

function findNextOpenBrace(source, start) {
  let quote = '', escaped = false, parens = 0;
  for (let index = start; index < source.length; index++) {
    const char = source[index];
    if (quote) {
      if (escaped) escaped = false;
      else if (char === '\\') escaped = true;
      else if (char === quote) quote = '';
    } else if (char === '"' || char === "'") quote = char;
    else if (char === '(' || char === '[') parens++;
    else if (char === ')' || char === ']') parens = Math.max(0, parens - 1);
    else if (char === '{' && parens === 0) return index;
  }
  return -1;
}

function findClosingBrace(source, opening) {
  let depth = 1, quote = '', escaped = false;
  for (let index = opening + 1; index < source.length; index++) {
    const char = source[index];
    if (quote) {
      if (escaped) escaped = false;
      else if (char === '\\') escaped = true;
      else if (char === quote) quote = '';
    } else if (char === '"' || char === "'") quote = char;
    else if (char === '{') depth++;
    else if (char === '}' && --depth === 0) return index;
  }
  return source.length;
}

export function extractCssRules(source, baseLine = 1, sourceOffset = 0) {
  const clean = stripComments(source), rules = [];
  let cursor = 0;
  while (cursor < clean.length) {
    const opening = findNextOpenBrace(clean, cursor);
    if (opening < 0) break;
    const closing = findClosingBrace(clean, opening);
    const selector = clean.slice(cursor, opening).trim();
    const body = clean.slice(opening + 1, closing);
    const selectorOffset = cursor + Math.max(0, clean.slice(cursor, opening).search(/\S/));
    const line = baseLine + clean.slice(0, selectorOffset).split('\n').length - 1;
    const bodyBaseLine = baseLine + clean.slice(0, opening + 1).split('\n').length - 1;
    const bodyStart = sourceOffset + opening + 1;
    const bodyEnd = sourceOffset + closing;
    if (selector.startsWith('@')) rules.push(...extractCssRules(body, bodyBaseLine, bodyStart));
    else if (selector) {
      rules.push({ selector, declarations: parseCssDeclarations(body), line, offset: sourceOffset + selectorOffset, bodyStart, bodyEnd });
      rules.push(...extractCssRules(body, bodyBaseLine, bodyStart));
    }
    cursor = closing + 1;
  }
  return rules;
}

export function isNaturalTextSelector(selector) {
  const branches = splitTopLevel(selector, ',');
  return branches.some(branch => {
    const trimmed = branch.trim();
    const targets = trimmed.split(/\s*[>+~]\s*|\s+/);
    const target = targets[targets.length - 1] || '';
    if (/(?:^|[\s>])(?:pre|code|kbd|samp)(?:\s|$)/i.test(trimmed)) return false;
    if (/\.(?:code-lines|code-block|code-sample|icon-heading)(?:[.#\s:[>+~]|$)/i.test(branch)) return false;
    if (/^(?:button|input|textarea|select|\.btn|\.button)(?:$|[.#:[>+~])/i.test(target)) return false;
    const tags = /(?:^|[\s>+~,(])(?:h[1-6]|p|li|dd|dt|summary|label|blockquote|figcaption|caption)(?=$|[\s.:#,[)>+~])/i;
    const classes = /(?:^|[.#\s:[>+~])(?:[\w-]*-)?(?:prose|copy(?:-text)?|description|intro(?:duction)?|help-text|text-content|content-text|text-column|paragraph|heading|title|headline|lead|subtitle)(?=$|[.#\s:[>+~])/i;
    const ids = /(?:^|[#\s>+~])#[\w-]*(?:prose|copy(?:-text)?|description|intro(?:duction)?|help-text|text-content|content-text|text-column|paragraph|heading|title|headline|lead|subtitle)(?=$|[.#\s:[>+~])/i;
    return tags.test(branch) || classes.test(branch) || ids.test(branch);
  });
}

function isParagraphMeasureSelector(selector) {
  if (/::|(?:^|[\s,>])(?:h[1-6]|button|input|textarea|select)(?:\b|$)/i.test(selector)) return false;
  return /(?:^|[\s>+~,(])(?:p|li|dd|blockquote|figcaption)(?=$|[\s.:#,[)>+~])/i.test(selector)
    || /(?:^|[.#\s:[>+~])(?:[\w-]*-)?(?:prose|copy(?:-text)?|description|intro(?:duction)?|help-text|text-content|content-text|text-column|paragraph|lead|subtitle)(?=$|[.#\s:[>+~])/i.test(selector);
}

export function isReadingRegionSelector(selector) {
  if (/(?:carousel[-_]image|image[-_]wrapper|image[-_]container|quality[-_]bar|particles[-_]container)/i.test(selector)) return false;
  if (/(?:^|[.#\s>])(?:nav(?:igation)?(?:[-_][\w-]*)?|tabs?list|tab-list|button-group)(?=$|[-_][\w-]*|[.#\s:[>+~])/i.test(selector)) return false;
  if (isParagraphMeasureSelector(selector) || /::|(?:^|[\s,>])(?:h[1-6]|button|input|textarea|select|pre|code|table|nav)(?:\b|$)/i.test(selector)) return false;
  if (/(?:^|[.#\s>])xp-(?:text|bar)(?=$|[-_][\w-]*|[.#\s:[>+~])/i.test(selector)) return false;
  if (/(?:^|[.#\s>])[\w-]*(?:[-_](?:badge|chip|tag|marker|label|btn|button|kicker|eyebrow|switcher-link|done))(?=$|[-_][\w-]*|[.#\s:[>+~])/i.test(selector)) return false;
  if (/(?:^|[.#\s>])(?:code|toast|notification|alert|search|progress|button|btn|form|input|control|filter|image|icon|avatar|badge|chip|tag)[\w-]*/i.test(selector)) return false;
  return /(?:^|[.#\s>+~,(])(?:main|article|section|aside|app|[\w-]*(?:container|content|context|reading|timeline|explanation|lesson|layout|column|copy|prose|paragraph|story|guide|page|shell|grid)[\w-]*|wrap(?:per)?|module|sec-head|section-header)(?=$|[.#\s:[>+~])/i.test(selector)
    || /(?:^|[.#\s>])(?:[\w-]+-)?text(?:-(?:content|column|copy|reading))?(?=$|[.#\s:[>+~])/i.test(selector);
}

function isOverlayContainerSelector(selector) {
  return /(?:dialog|modal|popover|dropdown|tooltip|toast|notification|decoder|device[-_]inspection|inspection[-_]shell)(?:[-_\w]*)/i.test(selector);
}

function findException(source, offset) {
  const before = source.slice(0, offset);
  const close = before.lastIndexOf('*/');
  if (close < 0 || /\S/.test(before.slice(close + 2))) return '';
  const open = before.lastIndexOf('/*', close);
  if (open < 0) return '';
  return before.slice(open + 2, close).match(/text-layout-exception:\s*(.{8,})/i)?.[1]?.trim() || '';
}

function resolveCssVariables(value, variables, seen = new Set()) {
  return String(value).replace(/var\(\s*(--[\w-]+)\s*(?:,\s*([^)]*))?\)/g, (_match, name, fallback = '') => {
    if (seen.has(name)) return fallback;
    const replacement = variables.get(name);
    return replacement === undefined ? fallback : resolveCssVariables(replacement, variables, new Set([...seen, name]));
  });
}

function isConstrainedMaxWidth(value, variables) {
  const resolved = resolveCssVariables(value, variables);
  if (/calc\([^)]*100%\s*-\s*[^)]*\)/i.test(resolved)) return false;
  return /\d(?:[.\d]*)(?:ch|px|r?em|vw)\b/i.test(resolved);
}

function declarationsFindings(selector, declarations, line, file, exception = '', variables = new Map()) {
  const naturalText = isNaturalTextSelector(selector);
  const readingRegion = isReadingRegionSelector(selector);
  if (!naturalText && !readingRegion) return { findings: [], exceptions: [] };
  const rules = [];
  const add = (rule, detail, property) => rules.push({ file, line, selector, rule, property, value: declarations[property], detail });
  if (naturalText || readingRegion) {
    if (/ellipsis/i.test(declarations['text-overflow'] || '')) add('content-truncation', 'El texto de contenido se trunca con puntos suspensivos.', 'text-overflow');
    if (declarations['line-clamp'] || declarations['-webkit-line-clamp']) add('content-line-clamp', 'El contenido tiene un límite de líneas.', declarations['-webkit-line-clamp'] ? '-webkit-line-clamp' : 'line-clamp');
    if (/\bnowrap\b/i.test(declarations['white-space'] || '')) add('content-no-wrap', 'El texto natural no permite el ajuste de línea.', 'white-space');
    if (/\bbreak-(?:all|word)\b/i.test(declarations['word-break'] || '')) add('forced-word-break', 'La propiedad word-break divide palabras de texto natural.', 'word-break');
    if (/\banywhere\b/i.test(declarations['overflow-wrap'] || declarations['word-wrap'] || '')) {
      const property = declarations['overflow-wrap'] ? 'overflow-wrap' : 'word-wrap';
      add('forced-word-break', 'overflow-wrap:anywhere puede reducir la columna al ancho de un carácter.', property);
    }
    if (/\bauto\b/i.test(declarations.hyphens || declarations['-webkit-hyphens'] || '')) add('automatic-hyphenation', 'La prosa divide palabras automáticamente.', 'hyphens');
  }
  for (const property of ['max-width', 'max-inline-size']) {
    const value = declarations[property] || '';
    if (isParagraphMeasureSelector(selector) && isConstrainedMaxWidth(value, variables)) {
      add('narrow-prose-measure', `La medida ${value} limita el ancho disponible de la prosa.`, property);
    }
  }
  if (isReadingRegionSelector(selector) && !isOverlayContainerSelector(selector)) {
    for (const property of ['max-width', 'max-inline-size']) {
      const value = declarations[property] || '';
      if (isConstrainedMaxWidth(value, variables)) add('narrow-reading-region', `La región intermedia está limitada a ${value}.`, property);
    }
    if (/\bgrid-template-columns\s*:[^;{}]*\bminmax\(\s*0\s*,\s*[\d.]+ch\s*\)/i.test(Object.entries(declarations).map(([key,value])=>`${key}:${value}`).join(';'))) {
      add('narrow-reading-column', 'Una columna de lectura conserva un tope medido en caracteres.', 'grid-template-columns');
    }
  }
  const percentWidth = declarations.width?.match(/^\s*(\d+(?:\.\d+)?)%\s*$/);
  if (isParagraphMeasureSelector(selector) && percentWidth && Number(percentWidth[1]) < 95) {
    add('narrow-prose-width', `El bloque usa width:${percentWidth[1]}% y no llena el ancho de su columna.`, 'width');
  }
  const dimension = declarations.height || declarations['max-height'] || declarations['block-size'] || declarations['max-block-size'];
  const hiddenByState = /\bnone\b/i.test(declarations.display || '')
    || /^(?:0(?:\.0+)?(?:px|rem|em|vh|vw|%)?)$/i.test(declarations['max-height'] || declarations['max-block-size'] || '');
  if ((naturalText || readingRegion) && !hiddenByState && /\b(?:hidden|clip)\b/i.test(declarations.overflow || '') && dimension && !/\b(?:auto|none|max-content|fit-content)\b/i.test(dimension)) {
    add('content-clipping', 'El contenedor recorta texto mediante overflow y una altura limitada.', 'overflow');
  }
  if (!rules.length) return { findings: [], exceptions: [] };
  if (exception) return { findings: [], exceptions: rules.map(item => ({ ...item, reason: exception })) };
  return { findings: rules, exceptions: [] };
}

export function scanStylesheet(source, file, baseLine = 1) {
  const findings = [], exceptions = [];
  const rules = extractCssRules(source, baseLine);
  const variables = new Map(rules.flatMap(rule => Object.entries(rule.declarations).filter(([key]) => key.startsWith('--'))));
  for (const rule of rules) {
    const result = declarationsFindings(rule.selector, rule.declarations, rule.line, file, findException(source, rule.offset), variables);
    findings.push(...result.findings);
    exceptions.push(...result.exceptions);
  }
  return { findings, exceptions };
}

function extractStyleBlocks(source) {
  const blocks = [];
  const matcher = /<style\b[^>]*>([\s\S]*?)<\/style\s*>/gi;
  let match;
  while ((match = matcher.exec(source))) {
    blocks.push({ text: match[1], line: source.slice(0, match.index).split('\n').length });
  }
  return blocks;
}

function scanMarkup(source, file) {
  const findings = [], exceptions = [];
  const tags = /<([a-z][\w:-]*)\b([^>]*)>/gi;
  let match;
  while ((match = tags.exec(source))) {
    const attrs = match[2];
    const classAttribute = attrs.match(/\bclass(?:Name)?\s*=\s*(?:"[^"]*"|'[^']*'|`[^`]*`|\{[^>]*\})/i)?.[0] || '';
    const attributeValue = classAttribute.slice(classAttribute.indexOf('=') + 1).trim();
    let classValue = attributeValue.slice(1, -1);
    if (attributeValue.startsWith('{')) {
      const expression = attributeValue.slice(1, -1);
      const templates = [...expression.matchAll(/`([^`]*)`/g)].map(([,value]) => value.replace(/\$\{[^}]*\}/g, ' '));
      const strings = [...expression.matchAll(/["']([^"']*)["']/g)].map(([,value]) => value);
      classValue = [...templates, ...strings].join(' ');
    }
    const selector = `${match[1]} ${classValue.split(/\s+/).filter(Boolean).map(item => `.${item}`).join(' ')}`;
    const naturalText = isNaturalTextSelector(selector);
    const readingRegion = isReadingRegionSelector(selector) && !isOverlayContainerSelector(selector);
    const classes = classValue.split(/\s+/);
    const truncatingUtility = classes.some(item => item === 'truncate' || /^line-clamp-\d+$/.test(item));
    const hiddenFromAssistiveTechnology = /\baria-hidden\s*=\s*["']true["']/i.test(attrs);
    if (!naturalText && !readingRegion && !(truncatingUtility && !hiddenFromAssistiveTechnology)) continue;
    const line = source.slice(0, match.index).split('\n').length;
    const declaredException = attrs.match(/\bdata-text-layout-exception\s*=\s*["']([^"']{8,})["']/i)?.[1]?.trim() || '';
    const commentException = source.slice(0, match.index).match(/<!--\s*text-layout-exception:\s*([^>]{8,})\s*-->\s*$/i)?.[1]?.trim() || '';
    const exception = declaredException || commentException;
    const utilityIssues = [];
    if (classes.includes('truncate')) utilityIssues.push(['content-truncation', 'La clase truncate recorta texto natural.']);
    if (classes.some(item => /^line-clamp-\d+$/.test(item))) utilityIssues.push(['content-line-clamp', 'La clase line-clamp limita el texto natural.']);
    if (classes.includes('break-all')) utilityIssues.push(['forced-word-break', 'La clase break-all divide palabras de texto natural.']);
    if (classes.includes('whitespace-nowrap')) utilityIssues.push(['content-no-wrap', 'La clase impide ajustar texto natural.']);
    const widthUtility = classes.map(item => item.split(':').at(-1)).find(item => {
      if (!item.startsWith('max-w-')) return false;
      const value = item.slice('max-w-'.length);
      if (['full', 'none', 'fit', 'min', 'max'].includes(value)) return false;
      return !/^\[(?:100%|calc\(100%\s*-\s*[^\]]+\))\]$/i.test(value);
    });
    if (widthUtility && (isParagraphMeasureSelector(selector) || readingRegion)) {
      utilityIssues.push([isParagraphMeasureSelector(selector) ? 'narrow-prose-measure' : 'narrow-reading-region', `La clase ${widthUtility} limita el ancho disponible.`]);
    }
    const inlineStyle = attrs.match(/\bstyle\s*=\s*["']([^"']*)["']/i)?.[1];
    const result = declarationsFindings(selector, inlineStyle ? parseCssDeclarations(inlineStyle) : {}, line, file, exception);
    const utilityFindings = utilityIssues.map(([rule, detail]) => ({ file, line, selector, rule, detail }));
    if (exception) exceptions.push(...utilityFindings.map(item => ({ ...item, reason: exception })));
    else findings.push(...utilityFindings);
    findings.push(...result.findings);
    exceptions.push(...result.exceptions);
  }
  return { findings, exceptions };
}

function scanFile(absolutePath, workspaceRoot) {
  const extension = extname(absolutePath).toLowerCase();
  const file = relative(workspaceRoot, absolutePath).split(sep).join('/');
  const source = readFileSync(absolutePath, 'utf8');
  if (['.css', '.scss', '.sass', '.less'].includes(extension)) return scanStylesheet(source, file);
  const results = [scanMarkup(source, file)];
  for (const block of extractStyleBlocks(source)) results.push(scanStylesheet(block.text, file, block.line));
  return { findings: results.flatMap(item => item.findings), exceptions: results.flatMap(item => item.exceptions) };
}

function walkStyleFiles(root) {
  const files = [], pending = [root];
  while (pending.length) {
    const current = pending.pop();
    for (const entry of readdirSync(current, { withFileTypes: true })) {
      const fullPath = resolve(current, entry.name);
      if (entry.isSymbolicLink()) continue;
      if (entry.isDirectory() && !SKIP_DIRECTORIES.has(entry.name.toLowerCase())) pending.push(fullPath);
      else if (entry.isFile() && STYLE_EXTENSIONS.has(extname(entry.name).toLowerCase()) && !isHashedCssBundle(fullPath)) files.push(fullPath);
    }
  }
  return files;
}

function isHashedCssBundle(path) {
  return /(?:^|[\\/])assets[\\/](?:index-)?[A-Za-z0-9_-]{8,}\.css$/i.test(path);
}

export function scanWorkspace(workspaceRoot, sourceRoots = SOURCE_ROOTS) {
  const root = resolve(workspaceRoot), scopes = [], findings = [], exceptions = [];
  let filesScanned = 0;
  for (const scopePath of sourceRoots) {
    const absolute = resolve(root, scopePath);
    const scope = { path: scopePath, exists: existsSync(absolute), filesScanned: 0, findings: 0 };
    if (scope.exists) {
      for (const filePath of walkStyleFiles(absolute)) {
        const result = scanFile(filePath, root);
        filesScanned++;
        scope.filesScanned++;
        scope.findings += result.findings.length;
        findings.push(...result.findings);
        exceptions.push(...result.exceptions);
      }
    }
    scopes.push(scope);
  }
  return { root, filesScanned, findings, exceptions, scopes };
}

export function parseArguments(argv) {
  const options = { root: '', failOnViolations: false, json: false, project: false };
  for (let index = 0; index < argv.length; index++) {
    if (argv[index] === '--root' && argv[index + 1]) options.root = argv[++index];
    else if (argv[index] === '--fail-on-violations') options.failOnViolations = true;
    else if (argv[index] === '--json') options.json = true;
    else if (argv[index] === '--project') options.project = true;
  }
  return options;
}

export function formatReport(report, json = false) {
  if (json) return JSON.stringify({ ...report, errors: report.findings.length }, null, 2);
  const lines = [`Auditoría de texto: ${report.filesScanned} archivos revisados, ${report.findings.length} hallazgo(s), ${report.exceptions.length} excepción(es).`];
  for (const finding of report.findings) lines.push(`  [${finding.rule}] ${finding.file}:${finding.line} ${finding.selector} — ${finding.detail}`);
  for (const scope of report.scopes) lines.push(`  ${scope.path}: ${scope.filesScanned} archivo(s), ${scope.findings} hallazgo(s).`);
  return lines.join('\n');
}

export function runAudit(argv, output = console) {
  const options = parseArguments(argv);
  const root = options.root || resolve(fileURLToPath(import.meta.url), '../../../..');
  const report = options.project ? scanWorkspace(root, ['.']) : scanWorkspace(root);
  output.log(formatReport(report, options.json));
  return options.failOnViolations && report.findings.length ? 1 : 0;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) process.exitCode = runAudit(process.argv.slice(2));
