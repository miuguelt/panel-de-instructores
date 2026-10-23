"""Suite de Pruebas de Invariantes Dorados de Aseo (Golden Invariants).

Garantiza de forma matemática y reproducible que el motor de Bolsa de Rondas
(Token Bucket) preserva sus invariantes sin importar cuántas nuevas funciones
o vistas se agreguen en el futuro:

1. Invariante 1 (Equidad Estricta): max(cargas) - min(cargas) <= 1 en cualquier horizonte.
2. Invariante 2 (Descanso Obligatorio): Cero asignaciones en sesiones consecutivas para cualquier aprendiz.
3. Invariante 3 (Diversidad de Parejas): Minimización de parejas repetidas mientras existan combinaciones inéditas.
4. Invariante 4 (Respeto de Ausencias y Exclusiones): Los aprendices excluidos o ausentes nunca reciben turno.
5. Invariante 5 (Respeto de Ajustes Manuales y Cumplidos): Los turnos históricos y manuales descuentan cupo sin duplicar.
6. Invariante 6 (Recálculo de No Cumplidos): Un turno no cumplido no infla cargas ficticias y se reprograma prioritariamente.
"""

from collections import Counter
from datetime import date, timedelta
import random
import unittest

from app import create_app, db
from app.models.aprendiz import Aprendiz
from app.models.aseo import TurnoAseo
from app.models.asistencia import SesionAsistencia
from app.models.ficha import Ficha
from app.models.instructor import Instructor
from app.services.aseo import generar_turnos, marcar_no_cumplido, completar_turno
from app.services.aseo_motor_puro import calcular_turnos_token_bucket
from tests.test_aseo_equidad import fechas_futuras


class TestAseoInvariantesDoradosPuros(unittest.TestCase):
    """Pruebas del motor puro con simulaciones de largo aliento (60 días, cohortes impares de 23 aprendices)."""

    def test_invariante_equidad_y_descanso_60_dias_cohorte_impar_23(self):
        """Simula 60 días continuos con 23 aprendices (caso real de producción) con 10 semillas aleatorias."""
        aprendiz_ids = list(range(1, 24))  # 23 aprendices
        fechas = [
            date(2026, 10, 1) + timedelta(days=i)
            for i in range(120)
            if (date(2026, 10, 1) + timedelta(days=i)).weekday() < 5
        ][:60]

        for seed in (7, 42, 99, 123, 777, 999, 2024, 2026, 31415, 65535):
            rng = random.Random(seed)
            res = calcular_turnos_token_bucket(
                aprendiz_ids=aprendiz_ids,
                sesiones_fechas=fechas,
                rng=rng,
            )

            asignaciones = res['asignaciones']
            self.assertEqual(len(asignaciones), 60)

            # Invariante 1: Diferencia máxima de cargas <= 1
            cargas = res['cargas_finales']
            delta = max(cargas.values()) - min(cargas.values())
            self.assertLessEqual(
                delta, 1,
                f"Semilla {seed}: Delta de cargas excedido ({delta}). Cargas: {cargas}"
            )

            # Invariante 2: Cero días consecutivos para cualquier aprendiz
            for i in range(len(asignaciones) - 1):
                t1 = {asignaciones[i]['aprendiz_1_id'], asignaciones[i]['aprendiz_2_id']}
                t2 = {asignaciones[i + 1]['aprendiz_1_id'], asignaciones[i + 1]['aprendiz_2_id']}
                interseccion = t1.intersection(t2)
                self.assertEqual(
                    len(interseccion), 0,
                    f"Semilla {seed}: Aprendiz {interseccion} asignado consecutivamente en {asignaciones[i]['fecha']} y {asignaciones[i+1]['fecha']}"
                )

    def test_invariante_diversidad_parejas_maximizada(self):
        """Verifica que en una rotación completa las parejas no se repitan mientras sea posible."""
        aprendiz_ids = list(range(1, 24))
        # 22 días = 44 cupos = casi 2 rondas completas (46 cupos)
        fechas = [
            date(2026, 10, 1) + timedelta(days=i)
            for i in range(40)
            if (date(2026, 10, 1) + timedelta(days=i)).weekday() < 5
        ][:22]

        res = calcular_turnos_token_bucket(
            aprendiz_ids=aprendiz_ids,
            sesiones_fechas=fechas,
            rng=random.Random(42),
        )

        parejas = [
            tuple(sorted((asig['aprendiz_1_id'], asig['aprendiz_2_id'])))
            for asig in res['asignaciones']
        ]
        # Con 22 sesiones y 23 aprendices, cada sesión debe tener una pareja única (0 repeticiones)
        self.assertEqual(len(set(parejas)), len(parejas), "Hubo parejas repetidas en el primer ciclo")

    def test_invariante_respeto_estricto_ausencias(self):
        """Simula ausencias aleatorias y garantiza que un ausente jamás sea asignado."""
        aprendiz_ids = list(range(1, 15))
        fechas = [
            date(2026, 10, 1) + timedelta(days=i)
            for i in range(30)
            if (date(2026, 10, 1) + timedelta(days=i)).weekday() < 5
        ][:20]

        rng = random.Random(888)
        ausentes_por_fecha = {}
        for f in rng.sample(fechas, 8):
            ausentes = set(rng.sample(aprendiz_ids, rng.randint(1, 3)))
            ausentes_por_fecha[f] = set(aprendiz_ids) - ausentes

        res = calcular_turnos_token_bucket(
            aprendiz_ids=aprendiz_ids,
            sesiones_fechas=fechas,
            ausentes_por_fecha=ausentes_por_fecha,
            rng=rng,
        )

        for asig in res['asignaciones']:
            f = asig['fecha']
            if f in ausentes_por_fecha:
                presentes = ausentes_por_fecha[f]
                self.assertIn(asig['aprendiz_1_id'], presentes)
                self.assertIn(asig['aprendiz_2_id'], presentes)

    def test_invariante_excluidos_sin_candidatos_y_grupo_minimo(self):
        """Verifica el comportamiento seguro ante exclusiones temporales, días sin candidatos y grupos de 2."""
        f1 = date(2026, 10, 5)
        f2 = date(2026, 10, 6)
        f3 = date(2026, 10, 7)

        # Caso 1: Solo 1 candidato elegible en f1 (el otro excluido hasta f1) -> f1 va a sin_candidatos
        res = calcular_turnos_token_bucket(
            aprendiz_ids=[1, 2],
            sesiones_fechas=[f1, f2, f3],
            excluidos_hasta={2: f1},
            rng=random.Random(10),
        )
        self.assertEqual(res['sin_candidatos'], [f1])
        self.assertEqual(len(res['asignaciones']), 2)
        # En f2 y f3 solo hay 2 aprendices en total, por lo que relaja el descanso sin bloquearse
        self.assertEqual({res['asignaciones'][0]['aprendiz_1_id'], res['asignaciones'][0]['aprendiz_2_id']}, {1, 2})
        self.assertEqual({res['asignaciones'][1]['aprendiz_1_id'], res['asignaciones'][1]['aprendiz_2_id']}, {1, 2})

    def test_snapshot_dorado_60d_coincide_con_archivo_y_hash(self):
        """Verifica que el snapshot dorado de 60 días exista, coincida con su hash SHA-256 en invariants.json y reproduzca los invariantes."""
        import hashlib
        import json
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[1]
        golden_path = repo_root / 'tests' / 'golden' / 'aseo_23_aprendices_60d.json'
        manifest_path = repo_root / '.devbrain' / 'invariants.json'

        self.assertTrue(golden_path.is_file(), f"Falta el snapshot dorado en {golden_path}")
        self.assertTrue(manifest_path.is_file(), f"Falta el manifiesto en {manifest_path}")

        raw_bytes = golden_path.read_bytes()
        # Git guarda el snapshot con LF y el checkout lo convierte a CRLF en
        # Windows: el hash se calcula sobre el contenido canónico para que la
        # misma revisión coincida en Linux (CI) y en Windows (local).
        canonical = raw_bytes.replace(b'\r\n', b'\n')
        actual_hash = "sha256:" + hashlib.sha256(canonical).hexdigest().lower()

        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest = json.load(f)

        expected_hash = manifest['modules']['turnos-aseo']['golden_hashes']['tests/golden/aseo_23_aprendices_60d.json'].lower()
        self.assertEqual(actual_hash, expected_hash, f"Hash del snapshot dorado alterado: {actual_hash} != {expected_hash}")

        data = json.loads(raw_bytes.decode('utf-8'))
        self.assertEqual(len(data['asignaciones']), 60)
        cargas = data['cargas_finales']
        delta = max(cargas.values()) - min(cargas.values())
        self.assertLessEqual(delta, 1)


class TestAseoInvariantesDoradosBaseDatos(unittest.TestCase):
    """Pruebas end-to-end con base de datos, SQLAlchemy, asistencias y ciclo de vida de turnos."""

    def setUp(self):
        self.app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_ENGINE_OPTIONS': {},
            'WTF_CSRF_ENABLED': False,
            'RATELIMIT_ENABLED': False,
        })
        self.contexto = self.app.app_context()
        self.contexto.push()
        db.create_all()

        self.instructor = Instructor(
            nombre='Instructor Invariantes',
            correo='instructor_invariantes@sena.edu.co',
            rol='instructor',
        )
        self.instructor.set_password('password123')
        db.session.add(self.instructor)
        db.session.flush()

        self.ficha = Ficha(
            codigo='9999991',
            nombre_programa='ADSO Invariantes',
            instructor_id=self.instructor.id,
            fecha_inicio=date(2026, 1, 1),
            fecha_fin=date(2027, 12, 31),
        )
        db.session.add(self.ficha)
        db.session.flush()

        # Cohorte real de 23 aprendices
        self.aprendices = []
        for i in range(1, 24):
            ap = Aprendiz(
                ficha_id=self.ficha.id,
                documento=f'1000000{i:02d}',
                nombre=f'Aprendiz_{i:02d}',
                apellidos=f'Apellido_{i:02d}',
                estado='EN_FORMACION',
            )
            db.session.add(ap)
            self.aprendices.append(ap)
        db.session.commit()

    def test_invariante_e2e_recalculo_no_repite_consecutivos_con_ajuste_manual(self):
        """Crea un mes de turnos con 23 aprendices, introduce un ajuste manual y recalcula.
        Verifica cero turnos consecutivos y delta <= 1.
        """
        fechas = fechas_futuras(22)

        for f in fechas:
            db.session.add(SesionAsistencia(ficha_id=self.ficha.id, fecha=f))
        db.session.commit()

        # Generar mes completo inicial
        res1 = generar_turnos(
            self.ficha.id,
            fechas[0],
            fechas[-1],
            rng=random.Random(101),
        )
        self.assertEqual(len(res1['creados']), 22)

        # Ajuste manual en la mitad del mes (día 10)
        t_manual = TurnoAseo.query.filter_by(
            ficha_id=self.ficha.id, fecha=fechas[9]
        ).first()
        t_manual.aprendiz_1_id = self.aprendices[0].id
        t_manual.aprendiz_2_id = self.aprendices[1].id
        t_manual.generado_por = 'instructor'
        db.session.commit()

        # Recalcular respetando el ajuste manual
        res2 = generar_turnos(
            self.ficha.id,
            fechas[0],
            fechas[-1],
            recalcular_existentes=True,
            respetar_manuales=True,
            rng=random.Random(202),
        )
        db.session.commit()

        # Verificar todos los turnos del mes
        turnos = TurnoAseo.query.filter(
            TurnoAseo.ficha_id == self.ficha.id,
            TurnoAseo.fecha.between(fechas[0], fechas[-1]),
        ).order_by(TurnoAseo.fecha).all()

        self.assertEqual(len(turnos), 22)
        # Verificar que el manual se preservó
        self.assertEqual(turnos[9].generado_por, 'instructor')
        self.assertEqual(turnos[9].aprendiz_1_id, self.aprendices[0].id)
        self.assertEqual(turnos[9].aprendiz_2_id, self.aprendices[1].id)

        # Invariante 2 en BD: cero repeticiones consecutivas
        for i in range(len(turnos) - 1):
            t1_ids = {turnos[i].aprendiz_1_id, turnos[i].aprendiz_2_id}
            t2_ids = {turnos[i + 1].aprendiz_1_id, turnos[i + 1].aprendiz_2_id}
            inter = t1_ids.intersection(t2_ids)
            self.assertEqual(
                len(inter), 0,
                f"Aprendices {inter} consecutivos en {turnos[i].fecha} y {turnos[i+1].fecha}"
            )

        # Invariante 1 en BD: equidad de cargas
        contador_cargas = Counter()
        for t in turnos:
            contador_cargas[t.aprendiz_1_id] += 1
            contador_cargas[t.aprendiz_2_id] += 1
        delta = max(contador_cargas.values()) - min(contador_cargas.values())
        self.assertLessEqual(delta, 1, f"Delta en base de datos excedido: {delta}")

    def test_invariante_e2e_no_cumplido_reprograma_prioritariamente(self):
        """Verifica que al marcar un turno como no_cumplido, los aprendices
        que no cumplieron (quedando con 0 cumplidos) son reprogramados
        prioritariamente sobre quienes ya tienen turnos cumplidos."""
        # Dejar activos solo los primeros 4 aprendices para aislar el cierre de ronda
        for ap in self.aprendices[4:]:
            ap.activo = False
        db.session.flush()

        f1 = date(2026, 11, 2)
        f2 = date(2026, 11, 3)
        f3 = date(2026, 11, 4)

        for f in (f1, f2, f3):
            db.session.add(SesionAsistencia(ficha_id=self.ficha.id, fecha=f))
        db.session.commit()

        # Turno 1 en f1 con aprendices 0 y 1
        t1 = TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=f1,
            aprendiz_1_id=self.aprendices[0].id,
            aprendiz_2_id=self.aprendices[1].id,
            estado='programado',
            generado_por='sistema',
        )
        db.session.add(t1)

        # Turno 2 en f2 con aprendices 2 y 3 (que sí cumplen)
        t2 = TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=f2,
            aprendiz_1_id=self.aprendices[2].id,
            aprendiz_2_id=self.aprendices[3].id,
            estado='cumplido',
            completado_1=True,
            completado_2=True,
            generado_por='sistema',
        )
        db.session.add(t2)
        db.session.commit()

        # Se marca t1 como no cumplido
        marcar_no_cumplido(t1, observacion='Inasistencia general')
        db.session.commit()
        self.assertEqual(t1.estado, 'no_cumplido')

        # Recalcular turnos para f3
        generar_turnos(
            self.ficha.id,
            f3,
            f3,
            recalcular_existentes=True,
            rng=random.Random(77),
        )
        db.session.commit()

        # En f3, los aprendices 0 y 1 tienen 0 cumplidos mientras 2 y 3 tienen 1 cumplido.
        # Por tanto, el turno de f3 DEBE asignarse exactamente a 0 y 1.
        t_f3 = TurnoAseo.query.filter_by(ficha_id=self.ficha.id, fecha=f3).first()
        self.assertIsNotNone(t_f3)
        self.assertEqual(
            {t_f3.aprendiz_1_id, t_f3.aprendiz_2_id},
            {self.aprendices[0].id, self.aprendices[1].id},
        )

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.contexto.pop()
