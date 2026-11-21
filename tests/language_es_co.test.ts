/**
 * tests/language_es_co.test.ts
 * # Managed by DevBrain es-CO Language Gate v1.0
 *
 * Validador nativo de español de Colombia (es-CO) para Vitest, Jest o node:test.
 * Políticas canónicas 5.0.1 y 7.3 de DevBrain (.antigravityrules).
 */
import fs from 'node:fs';
import path from 'node:path';

const AUDIT_EXTENSIONS = new Set([
  '.ts', '.tsx', '.js', '.jsx', '.html', '.htm', '.vue', '.astro', '.svelte', '.md'
]);

const EXCLUDE_DIRS = new Set([
  '.git', '.venv', 'venv', 'venv_win', 'venv_wsl', 'env',
  'node_modules', 'dist', 'build', 'coverage', '.pytest_cache',
  '__pycache__', 'htmlcov', '.mypy_cache', 'playwright-report',
  'test-results', 'logs', 'scratch', '.agents', 'vendor'
]);

const EXCLUDE_FILES = new Set([
  'language_es_co.test.ts', 'language_es_co.test.mjs', 'test_es_co_language.py',
  'eslint-plugin-devbrain.js', 'es-co-lexicon.json', 'validate-rules.ps1', 'post-edit-hook.ps1',
  '.antigravityrules', '.cursorrules', '.windsurfrules',
  'AGENTS.md', 'GEMINI.md', 'CLAUDE.md'
]);

function findProjectRoot(startDir: string): string {
  let curr = path.resolve(startDir);
  for (let i = 0; i < 6; i++) {
    if (fs.existsSync(path.join(curr, 'package.json')) || fs.existsSync(path.join(curr, '.git'))) {
      return curr;
    }
    const parent = path.dirname(curr);
    if (parent === curr) break;
    curr = parent;
  }
  return path.resolve(startDir);
}

function findLexiconFile(projectRoot: string): string | null {
  let curr = projectRoot;
  for (let i = 0; i < 6; i++) {
    const candidate = path.join(curr, '_core', 'knowledge_base', 'rules', 'es-co-lexicon.json');
    if (fs.existsSync(candidate)) return candidate;
    const parent = path.dirname(curr);
    if (parent === curr) break;
    curr = parent;
  }
  return null;
}

function isPathExcluded(relPath: string, excludePaths: Array<{ path?: string } | string>): boolean {
  const relClean = relPath.replace(/\\/g, '/').replace(/^\/+/, '').toLowerCase();
  for (const item of excludePaths) {
    const raw = typeof item === 'string' ? item : item?.path || '';
    const target = raw.replace(/\\/g, '/').replace(/^\/+|\/+$/g, '').toLowerCase();
    if (!target) continue;
    if (relClean === target || relClean.endsWith('/' + target) || target.endsWith('/' + relClean)) {
      return true;
    }
    if (relClean.startsWith(target + '/')) return true;
  }
  return false;
}

function isTermExcepted(
  term: string,
  line: string,
  index: number,
  exceptions: any[],
  relPath: string
): boolean {
  const relClean = relPath.replace(/\\/g, '/').replace(/^\/+/, '').toLowerCase();
  for (const exc of exceptions) {
    if (!exc || typeof exc !== 'object') continue;
    const excFile = (exc.file || '').replace(/\\/g, '/').replace(/^\/+|\/+$/g, '').toLowerCase();
    if (excFile && !(relClean === excFile || relClean.endsWith('/' + excFile) || excFile.endsWith('/' + relClean))) {
      continue;
    }
    if ((exc.term || '').trim().toLowerCase() !== term.trim().toLowerCase()) continue;

    let beforeOk = true;
    let afterOk = true;

    if (exc.context_before) {
      const len = exc.context_before.length;
      beforeOk = index >= len && line.substring(index - len, index).toLowerCase() === exc.context_before.toLowerCase();
    }
    if (exc.context_after) {
      const endIdx = index + term.length;
      const len = exc.context_after.length;
      afterOk = endIdx + len <= line.length && line.substring(endIdx, endIdx + len).toLowerCase() === exc.context_after.toLowerCase();
    }

    if (beforeOk && afterOk) return true;
  }
  return false;
}

export function validateColombianSpanish(testDir: string = __dirname): string[] {
  const projectRoot = findProjectRoot(testDir);
  const lexiconPath = findLexiconFile(projectRoot);

  let terms: any[] = [];
  let allowlist = new Set<string>();
  let excludePaths: any[] = [];
  let exceptions: any[] = [];

  if (lexiconPath && fs.existsSync(lexiconPath)) {
    const raw = JSON.parse(fs.readFileSync(lexiconPath, 'utf8'));
    terms = raw.terms || [];
    allowlist = new Set((raw.allowlist || []).map((t: any) => (t.term || '').trim().toLowerCase()));
    excludePaths = raw.scan?.exclude_paths || [];
    for (const f of raw.scan?.exclude_files || []) {
      EXCLUDE_FILES.add(f);
    }
    exceptions = raw.known_exceptions || [];
  } else {
    terms = [
      { term: 'ordenador', pattern: '\\bordenador(es)?\\b', replacement: 'computador' },
      { term: 'coche', pattern: '\\bcoche(s)?\\b', replacement: 'carro / vehículo' },
      { term: 'computadora', pattern: '\\bcomputadora(s)?\\b', replacement: 'computador' },
      { term: 'ratón', pattern: '\\brat[oó]n(es)?\\b', replacement: 'mouse' },
      { term: 'fichero', pattern: '\\bfichero(s)?\\b', replacement: 'archivo' },
      { term: 'pulsar', pattern: '\\bpulsar\\b|\\bpulse\\b|\\bpulsa\\b', replacement: 'hacer clic / presionar' },
      { term: 'dossier', pattern: '\\bdossier(s)?\\b', replacement: 'Portafolio de Evidencias' }
    ];
  }

  const compiledTerms = terms
    .map((t) => {
      try {
        return { term: t.term, regex: new RegExp(t.pattern, 'gi'), replacement: t.replacement || '' };
      } catch {
        return null;
      }
    })
    .filter(Boolean) as Array<{ term: string; regex: RegExp; replacement: string }>;

  const localeRegex = /['"]es-ES['"]/gi;
  const violations: string[] = [];

  function walk(currentDir: string) {
    const entries = fs.readdirSync(currentDir, { withFileTypes: true });
    for (const entry of entries) {
      if (entry.isDirectory()) {
        if (EXCLUDE_DIRS.has(entry.name) || entry.name.startsWith('.')) continue;
        if (entry.name === 'tests' || entry.name === 'test' || entry.name === '__tests__') continue;
        walk(path.join(currentDir, entry.name));
      } else if (entry.isFile()) {
        if (EXCLUDE_FILES.has(entry.name) || entry.name.includes('.test.') || entry.name.includes('.spec.')) continue;
        const ext = path.extname(entry.name).toLowerCase();
        if (!AUDIT_EXTENSIONS.has(ext)) continue;

        const fullPath = path.join(currentDir, entry.name);
        const relPath = path.relative(projectRoot, fullPath).replace(/\\/g, '/');
        if (isPathExcluded(relPath, excludePaths)) continue;

        let content = '';
        try {
          content = fs.readFileSync(fullPath, 'utf8');
        } catch {
          continue;
        }

        // Regla 7.2a
        let match: RegExpExecArray | null;
        while ((match = localeRegex.exec(content)) !== null) {
          const lineNo = content.substring(0, match.index).split('\n').length;
          violations.push(`${relPath}:${lineNo} [Regla 7.2a] 'es-ES' detectado -> usar 'es-CO'`);
        }

        // Regla 7.3
        const lines = content.split(/\r?\n/);
        lines.forEach((line, lineIdx) => {
          for (const item of compiledTerms) {
            item.regex.lastIndex = 0;
            let termMatch: RegExpExecArray | null;
            while ((termMatch = item.regex.exec(line)) !== null) {
              const matchedWord = termMatch[0].trim().toLowerCase();
              if (allowlist.has(matchedWord)) continue;
              if (isTermExcepted(item.term, line, termMatch.index, exceptions, relPath)) continue;

              violations.push(
                `${relPath}:${lineIdx + 1} [Regla 7.3] Término foráneo '${termMatch[0]}' detectado -> usar '${item.replacement}'`
              );
            }
          }
        });
      }
    }
  }

  walk(projectRoot);
  return violations;
}

// Ejecutor agnóstico de pruebas
const runnerDescribe = (globalThis as any).describe || ((name: string, fn: () => void) => fn());
const runnerIt = (globalThis as any).it || (globalThis as any).test;

if (typeof runnerIt === 'function') {
  runnerDescribe('Validación de Español de Colombia (es-CO)', () => {
    runnerIt('no debe contener términos foráneos ni tags es-ES', () => {
      const violations = validateColombianSpanish(__dirname);
      if (violations.length > 0) {
        throw new Error(
          `Violaciones léxicas de español de Colombia detectadas (${violations.length}):\n` +
          violations.slice(0, 15).map((v) => `  - ${v}`).join('\n')
        );
      }
    });
  });
}
