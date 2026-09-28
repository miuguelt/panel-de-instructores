import os
import unittest
import re

class HTMLSyntaxTestCase(unittest.TestCase):
    def test_html_templates_are_balanced(self):
        """
        Prueba básica para asegurar que los archivos HTML críticos no tengan
        un desbalance grosero de etiquetas <div> u otras anomalías de cierre.
        """
        templates_dir = os.path.join(os.path.dirname(__file__), '..', 'app', 'templates')
        
        archivos_a_verificar = [
            os.path.join('grupos', 'listar_grupos.html'),
            os.path.join('grupos', 'podio_grupos.html'),
            os.path.join('instructor', 'fila_atencion.html'),
            os.path.join('aprendiz', 'panel.html'),
        ]
        
        for rel_path in archivos_a_verificar:
            path = os.path.join(templates_dir, rel_path)
            if not os.path.exists(path):
                continue
                
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            # Eliminar bloques condicionales simples (if/else) de jinja para no contar duplicados de <div> condicionales
            # Esto es un reemplazo muy simple, pero efectivo para evitar falsos positivos
            content_sin_ifs = re.sub(r'\{%\s*(if|elif|else|endif).*?%\}', '', content)
            
            div_opens = len(re.findall(r'<div\b[^>]*>', content_sin_ifs))
            div_closes = len(re.findall(r'</div>', content_sin_ifs))
            
            self.assertEqual(
                div_opens, 
                div_closes, 
                f"El archivo {rel_path} tiene {div_opens} divs abiertos y {div_closes} cerrados. "
                "Revisa que no se haya borrado una etiqueta de cierre o apertura accidentalmente."
            )
