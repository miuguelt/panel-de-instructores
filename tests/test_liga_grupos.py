"""Pruebas unitarias para la liga de escuadrones y gamificación grupal formativa."""

from datetime import date, datetime, timedelta
import unittest

from app import create_app, db
from app.models.aprendiz import Aprendiz
from app.models.ficha import Ficha
from app.models.grupo import Grupo, GrupoAprendiz
from app.models.insignia import Insignia, InsigniaOtorgada
from app.models.instructor import Instructor
from app.models.tarea import Entrega, Tarea
from app.services.liga_grupos import (
    obtener_liga_grupos,
    obtener_resumen_escuadron,
)


class LigaGruposTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_ENGINE_OPTIONS': {},
            'WTF_CSRF_ENABLED': False,
            'RATELIMIT_ENABLED': False,
        })
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

        self.instructor = Instructor(
            nombre='Instructor Liga',
            correo='liga@sena.edu.co',
            rol='instructor',
        )
        self.instructor.set_password('segura123')
        db.session.add(self.instructor)
        db.session.flush()

        self.ficha = Ficha(
            codigo='2900002',
            codigo_ficha='2900002',
            nombre_programa='ADSO',
            instructor_id=self.instructor.id,
            fecha_inicio=date(2026, 1, 1),
            fecha_fin=date(2026, 12, 31),
        )
        db.session.add(self.ficha)
        db.session.flush()

        # Aprendices
        self.ap1 = Aprendiz(
            documento='1001', nombre='Ana', apellidos='Ríos',
            ficha_id=self.ficha.id, estado='EN_FORMACION',
        )
        self.ap2 = Aprendiz(
            documento='1002', nombre='Carlos', apellidos='Pérez',
            ficha_id=self.ficha.id, estado='EN_FORMACION',
        )
        self.ap3 = Aprendiz(
            documento='1003', nombre='Diana', apellidos='Gómez',
            ficha_id=self.ficha.id, estado='EN_FORMACION',
        )
        db.session.add_all([self.ap1, self.ap2, self.ap3])
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_obtener_liga_grupos_vacia(self):
        """Si la ficha no tiene grupos, la liga retorna una lista vacía."""
        liga = obtener_liga_grupos(self.ficha.id)
        self.assertEqual(liga, [])

    def test_obtener_liga_grupos_con_medallas_y_tareas(self):
        """Calcula el podio sumando 15 pts por medalla y 10 pts por tarea a tiempo."""
        g1 = Grupo(ficha_id=self.ficha.id, nombre='Alpha', activo=True)
        g2 = Grupo(ficha_id=self.ficha.id, nombre='Beta', activo=True)
        db.session.add_all([g1, g2])
        db.session.flush()

        m1 = GrupoAprendiz(grupo_id=g1.id, aprendiz_id=self.ap1.id)
        m2 = GrupoAprendiz(grupo_id=g2.id, aprendiz_id=self.ap2.id)
        db.session.add_all([m1, m2])
        db.session.flush()

        insignia = Insignia(
            ficha_id=self.ficha.id,
            nombre='Reto Oro',
            icono='🏆',
            descripcion='Desafío',
        )
        db.session.add(insignia)
        db.session.flush()

        # Otorgar medalla a g1 (+15 pts)
        ot = InsigniaOtorgada(
            grupo_id=g1.id,
            insignia_id=insignia.id,
            instructor_id=self.instructor.id,
        )
        db.session.add(ot)

        # Crear tarea y entrega de g1 a tiempo (+10 pts)
        tarea = Tarea(
            ficha_id=self.ficha.id,
            instructor_id=self.instructor.id,
            titulo='Reto 1',
            es_grupal=True,
            fecha_limite=datetime.now() + timedelta(days=2),
        )
        db.session.add(tarea)
        db.session.flush()

        entrega = Entrega(
            tarea_id=tarea.id,
            aprendiz_id=self.ap1.id,
            grupo_id=g1.id,
        )
        db.session.add(entrega)
        db.session.commit()

        liga = obtener_liga_grupos(self.ficha.id)
        self.assertEqual(len(liga), 2)
        # g1 debe liderar con 25 pts (15 medalla + 10 tarea)
        self.assertEqual(liga[0]['nombre'], 'Alpha')
        self.assertEqual(liga[0]['puntaje_grupo'], 25)
        self.assertEqual(liga[0]['podio'], '🥇')
        self.assertEqual(liga[0]['medallas_count'], 1)
        self.assertEqual(liga[0]['tareas_entregadas'], 1)

        # g2 queda segundo con 0 pts
        self.assertEqual(liga[1]['nombre'], 'Beta')
        self.assertEqual(liga[1]['puntaje_grupo'], 0)
        self.assertEqual(liga[1]['podio'], '🥈')

    def test_obtener_resumen_escuadron(self):
        """Verifica que un aprendiz reciba el resumen correcto de su equipo y None si no tiene."""
        resumen_sin_grupo = obtener_resumen_escuadron(self.ficha.id, self.ap3.id)
        self.assertIsNone(resumen_sin_grupo)

        g = Grupo(ficha_id=self.ficha.id, nombre='Gamma', activo=True)
        db.session.add(g)
        db.session.flush()
        db.session.add(GrupoAprendiz(grupo_id=g.id, aprendiz_id=self.ap3.id))
        db.session.commit()

        resumen_con_grupo = obtener_resumen_escuadron(self.ficha.id, self.ap3.id)
        self.assertIsNotNone(resumen_con_grupo)
        self.assertEqual(resumen_con_grupo['nombre'], 'Gamma')
        self.assertEqual(resumen_con_grupo['posicion'], 1)
        self.assertEqual(resumen_con_grupo['podio'], '🥇')
