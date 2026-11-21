"""
tests/test_es_co_language.py
# Managed by DevBrain es-CO Language Gate v1.0

Validador nativo de español de Colombia (es-CO) para pytest.
Políticas canónicas 5.0.1 y 7.3 de DevBrain (.antigravityrules).
Ejecuta standalone sin requerir PowerShell ni estado global.
"""
import json
import os
import re
from pathlib import Path

AUDIT_EXTENSIONS = {
    ".py", ".html", ".htm", ".ts", ".tsx", ".js", ".jsx",
    ".vue", ".astro", ".svelte", ".md"
}

EXCLUDE_DIRS = {
    ".git", ".venv", "venv", "venv_win", "venv_wsl", "env",
    "node_modules", "dist", "build", "coverage", ".pytest_cache",
    "__pycache__", "htmlcov", ".mypy_cache", "playwright-report",
    "test-results", "logs", "scratch", ".agents", "vendor"
}

EXCLUDE_FILES = {
    "test_es_co_language.py", "language_es_co.test.ts", "language_es_co.test.mjs",
    "eslint-plugin-devbrain.js", "es-co-lexicon.json", "validate-rules.ps1", "post-edit-hook.ps1",
    ".antigravityrules", ".cursorrules", ".windsurfrules",
    "AGENTS.md", "GEMINI.md", "CLAUDE.md"
}

def find_project_root(start: Path) -> Path:
    current = start.resolve()
    for _ in range(6):
        if (current / ".git").exists() or (current / "pyproject.toml").exists() or (current / "requirements.txt").exists():
            return current
        if current.parent == current:
            break
        current = current.parent
    return start.resolve()

def find_lexicon_file(project_root: Path) -> Path | None:
    current = project_root
    for _ in range(6):
        candidate = current / "_core" / "knowledge_base" / "rules" / "es-co-lexicon.json"
        if candidate.is_file():
            return candidate
        if current.parent == current:
            break
        current = current.parent
    return None

def normalize_rel_path(p: Path, root: Path) -> str:
    try:
        return p.resolve().relative_to(root.resolve()).as_posix().lower()
    except Exception:
        return p.as_posix().lower()

def is_path_excluded(rel_path: str, exclude_paths: list) -> bool:
    rel_clean = rel_path.strip("/").lower()
    for item in exclude_paths:
        raw_path = (item.get("path") if isinstance(item, dict) else str(item)) or ""
        target = raw_path.replace("\\", "/").strip("/").lower()
        if not target:
            continue
        if rel_clean == target or rel_clean.endswith("/" + target) or target.endswith("/" + rel_clean):
            return True
        if rel_clean.startswith(target + "/"):
            return True
    return False

def is_term_excepted(term: str, line: str, start_idx: int, exceptions: list, rel_path: str) -> bool:
    rel_clean = rel_path.strip("/").lower()
    for exc in exceptions:
        if not isinstance(exc, dict):
            continue
        exc_file = (exc.get("file") or "").replace("\\", "/").strip("/").lower()
        if exc_file and not (rel_clean == exc_file or rel_clean.endswith("/" + exc_file) or exc_file.endswith("/" + rel_clean)):
            continue
        if exc.get("term", "").strip().lower() != term.strip().lower():
            continue
        
        ctx_before = exc.get("context_before")
        ctx_after = exc.get("context_after")
        before_ok = True
        after_ok = True
        
        if ctx_before:
            needed = len(ctx_before)
            before_ok = (start_idx >= needed) and (line[start_idx - needed : start_idx].lower() == ctx_before.lower())
        if ctx_after:
            end_idx = start_idx + len(term)
            needed = len(ctx_after)
            after_ok = (end_idx + needed <= len(line)) and (line[end_idx : end_idx + needed].lower() == ctx_after.lower())
            
        if before_ok and after_ok:
            return True
    return False

def test_es_co_language_compliance():
    test_dir = Path(__file__).resolve().parent
    project_root = find_project_root(test_dir)
    lexicon_path = find_lexicon_file(project_root)
    
    if lexicon_path and lexicon_path.is_file():
        with open(lexicon_path, "r", encoding="utf-8") as f:
            lexicon = json.load(f)
        terms = lexicon.get("terms", [])
        allowlist = {t.get("term", "").strip().lower() for t in lexicon.get("allowlist", [])}
        exclude_paths = lexicon.get("scan", {}).get("exclude_paths", [])
        for f in lexicon.get("scan", {}).get("exclude_files", []):
            EXCLUDE_FILES.add(f)
        exceptions = lexicon.get("known_exceptions", [])
    else:
        terms = [
            {"term": "ordenador", "pattern": r"\bordenador(es)?\b", "replacement": "computador"},
            {"term": "coche", "pattern": r"\bcoche(s)?\b", "replacement": "carro / vehículo"},
            {"term": "computadora", "pattern": r"\bcomputadora(s)?\b", "replacement": "computador"},
            {"term": "ratón", "pattern": r"\brat[oó]n(es)?\b", "replacement": "mouse"},
            {"term": "fichero", "pattern": r"\bfichero(s)?\b", "replacement": "archivo"},
            {"term": "pulsar", "pattern": r"\bpulsar\b|\bpulse\b|\bpulsa\b", "replacement": "hacer clic / presionar"},
            {"term": "dossier", "pattern": r"\bdossier(s)?\b", "replacement": "Portafolio de Evidencias"},
        ]
        allowlist = set()
        exclude_paths = []
        exceptions = []

    compiled_terms = []
    for item in terms:
        try:
            compiled_terms.append((item["term"], re.compile(item["pattern"], re.IGNORECASE), item.get("replacement", "")))
        except Exception:
            continue

    locale_pattern = re.compile(r"['\"]es-ES['\"]", re.IGNORECASE)
    violations = []

    for root, dirs, files in os.walk(project_root):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS and not d.startswith(".")]
        if any(seg in {"tests", "test", "__tests__"} for seg in Path(root).parts):
            continue

        for file in files:
            if file in EXCLUDE_FILES or file.startswith("test_") or file.endswith(("_test.py", ".test.ts", ".test.js")):
                continue
            ext = Path(file).suffix.lower()
            if ext not in AUDIT_EXTENSIONS:
                continue

            file_path = Path(root) / file
            rel_path = normalize_rel_path(file_path, project_root)
            if is_path_excluded(rel_path, exclude_paths):
                continue

            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            # Regla 7.2a: Tag locale
            for match in locale_pattern.finditer(content):
                line_no = content[:match.start()].count("\n") + 1
                violations.append(f"{rel_path}:{line_no} [Regla 7.2a] 'es-ES' detectado -> usar 'es-CO'")

            # Regla 7.3: Léxico
            lines = content.splitlines()
            for line_idx, line in enumerate(lines, 1):
                for term_name, rgx, replacement in compiled_terms:
                    for m in rgx.finditer(line):
                        matched = m.group(0).strip().lower()
                        if matched in allowlist:
                            continue
                        if is_term_excepted(term_name, line, m.start(), exceptions, rel_path):
                            continue
                        violations.append(
                            f"{rel_path}:{line_idx} [Regla 7.3] Término foráneo '{m.group(0)}' detectado -> usar '{replacement}'"
                        )

    assert not violations, (
        f"Se encontraron {len(violations)} violaciones de español de Colombia (Reglas 5.0.1 y 7.3):\n"
        + "\n".join(f"  - {v}" for v in violations[:15])
        + (f"\n  ... y {len(violations)-15} más" if len(violations) > 15 else "")
    )
