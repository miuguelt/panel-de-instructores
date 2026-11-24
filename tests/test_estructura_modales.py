"""Every modal built on .app-modal-content must use the header/body/footer
structure, because only those regions carry the inner padding. Content placed
directly in the shell touches the edges (bug seen in the instructor portfolio
modal)."""
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parents[1] / 'app' / 'templates'
VOID = {'input', 'br', 'img', 'meta', 'link', 'hr', 'source', 'col', 'wbr'}
REGIONS = {'app-modal-header', 'app-modal-toolbar', 'app-modal-body', 'app-modal-footer'}
CONTROLS = {'input', 'select', 'textarea', 'button', 'label', 'p'}


def _strip_jinja(text):
    return re.sub(r'{%.*?%}|{{.*?}}|{#.*?#}', '', text, flags=re.S)


class _ModalAudit(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack = []  # list of (tag, classes, attrs)
        self.problems = []
        self.modals = []  # per modal: set of regions found

    def _classes(self):
        return [set(cls) for _, cls, _ in self.stack]

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = set((attrs.get('class') or '').split())
        ancestors = self._classes()
        in_modal = any('app-modal-content' in c for c in ancestors)
        in_region = any(c & REGIONS for c in ancestors)
        line = self.getpos()[0]

        if tag == 'dialog' and 'app-modal-overlay' in classes and attrs.get('style'):
            self.problems.append(f'line {line}: inline style on dialog overrides overlay')
        if 'app-modal-content' in classes:
            self.modals.append(set())
        if in_modal and classes & REGIONS:
            self.modals[-1].update(classes & REGIONS)
        if 'app-modal-footer' in classes and any('app-modal-body' in c for c in ancestors):
            self.problems.append(f'line {line}: footer nested inside body (double padding)')
        if in_modal and not in_region and tag in CONTROLS and attrs.get('type') != 'hidden':
            self.problems.append(f'line {line}: <{tag}> outside header/body/footer touches the edges')

        if tag not in VOID:
            self.stack.append((tag, classes, attrs))

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        while self.stack:
            if self.stack.pop()[0] == tag:
                break


def _audit(path):
    parser = _ModalAudit()
    parser.feed(_strip_jinja(path.read_text(encoding='utf-8')))
    problems = list(parser.problems)
    for index, regions in enumerate(parser.modals, 1):
        # A confirmation dialog may carry its message in the header and only a footer.
        if 'app-modal-header' not in regions or not regions & {'app-modal-body', 'app-modal-footer'}:
            problems.append(f'modal #{index} lacks header or body region: {sorted(regions)}')
    return problems


class EstructuraModalesTest(unittest.TestCase):
    def test_todos_los_modales_usan_regiones_con_margen(self):
        archivos = [p for p in TEMPLATES.rglob('*.html') if 'app-modal-content' in p.read_text(encoding='utf-8')]
        self.assertGreater(len(archivos), 5)
        fallas = {str(p.relative_to(TEMPLATES)): _audit(p) for p in archivos}
        fallas = {k: v for k, v in fallas.items() if v}
        self.assertEqual(fallas, {})

    def test_auditor_detecta_contenido_pegado_al_borde(self):
        html = ('<dialog class="app-modal-overlay" style="padding:0"><div class="app-modal-content">'
                '<header><h3>T</h3></header><form><input type="url"></form></div></dialog>')
        parser = _ModalAudit()
        parser.feed(html)
        self.assertTrue(any('inline style' in p for p in parser.problems))
        self.assertTrue(any('<input>' in p for p in parser.problems))
        self.assertEqual(parser.modals, [set()])

    def test_auditor_detecta_pie_dentro_del_cuerpo(self):
        html = ('<div class="app-modal-content"><header class="app-modal-header"></header>'
                '<form class="app-modal-body"><footer class="app-modal-footer"></footer></form></div>')
        parser = _ModalAudit()
        parser.feed(html)
        self.assertTrue(any('footer nested' in p for p in parser.problems))

    def test_auditor_acepta_modal_bien_formado(self):
        html = ('<dialog class="app-modal-overlay"><div class="app-modal-content">'
                '<header class="app-modal-header"><h2>T</h2><button>x</button></header>'
                '<form class="app-modal-form"><div class="app-modal-body"><input type="url"></div>'
                '<footer class="app-modal-footer"><button>Ok</button></footer></form></div></dialog>')
        self.assertEqual(_audit_text(html), [])


def _audit_text(html):
    parser = _ModalAudit()
    parser.feed(html)
    return parser.problems


if __name__ == '__main__':
    unittest.main()
