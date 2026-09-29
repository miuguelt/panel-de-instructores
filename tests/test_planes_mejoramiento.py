import os
import re
import tempfile
import unittest
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from io import BytesIO

from flask import g

from app import create_app, db
from app.models import (
    Aprendiz,
    ConfiguracionAlertas,
    ConfiguracionAlertasComite,
    ConfiguracionAseo,
    ConfiguracionRanking,
    Entrega,
    Ficha,
    Instructor,
    PlanMejoramiento,
    RegistroAsistencia,
    SesionAsistencia,
    ProrrogaTarea,
    Tarea,
    TurnoAtencion,
)


class _TarjetasTareaParser(HTMLParser):
    """Recoge cada tarjeta de tarea y sus elementos para asertar el render."""

    def __init__(self):
        super().__init__()
        self.tarjetas = []
        self._actual = None
        self._profundidad_div = 0

    def handle_starttag(self, tag, attrs):
        atributos = dict(attrs)
        if self._actual is None:
            if tag == 'div' and 'data-task-item' in atributos:
                self._actual = {
                    'atributos': atributos,
                    'elementos': [],
                    'texto': [],
                }
                self._profundidad_div = 1
            return

        self._actual['elementos'].append((tag, atributos))
        if tag == 'div':
            self._profundidad_div += 1

    def handle_endtag(self, tag):
        if self._actual is None or tag != 'div':
            return
        self._profundidad_div -= 1
        if self._profundidad_div == 0:
            self.tarjetas.append(self._actual)
            self._actual = None

    def handle_data(self, data):
        if self._actual is not None:
            self._actual['texto'].append(data)


class _FormulariosParser(HTMLParser):
    """Recoge formularios y campos para verificar el envío que verá el navegador."""

    def __init__(self):
        super().__init__()
        self.formularios = []
        self._actual = None

    def handle_starttag(self, tag, attrs):
        atributos = dict(attrs)
        if tag == 'form':
            self._actual = {'atributos': atributos, 'campos': {}}
        elif tag == 'input' and self._actual is not None:
            nombre = atributos.get('name')
            if nombre:
                self._actual['campos'][nombre] = atributos.get('value', '')

    def handle_endtag(self, tag):
        if tag == 'form' and self._actual is not None:
            self.formularios.append(self._actual)
            self._actual = None


class _TarjetasProgresoParser(HTMLParser):
    """Asocia cada barra de progreso con el nombre de la métrica que muestra."""

    def __init__(self):
        super().__init__()
        self.tarjetas = []
        self._actual = None
        self._profundidad = 0
        self._capturando_etiqueta = False

    def handle_starttag(self, tag, attrs):
        atributos = dict(attrs)
        clases = set(atributos.get('class', '').split())
        if self._actual is None:
            if tag == 'div' and 'progress-card' in clases:
                self._actual = {'barra': None, 'etiqueta': '', 'valor': ''}
                self._profundidad = 1
            return

        if tag == 'div':
            self._profundidad += 1
        if tag == 'div' and 'progress-card-track' in clases:
            self._actual['barra'] = atributos
        if tag == 'span' and 'progress-card-label' in clases:
            self._capturando_etiqueta = True
        elif tag == 'span' and 'progress-card-value' in clases:
            self._capturando_etiqueta = False
            self._actual['_capturando_valor'] = True

    def handle_endtag(self, tag):
        if self._actual is None:
            return
        if self._actual is not None and tag == 'span':
            self._capturando_etiqueta = False
            self._actual['_capturando_valor'] = False
            return
        if tag != 'div':
            return
        self._profundidad -= 1
        if self._profundidad == 0:
            self.tarjetas.append(self._actual)
            self._actual = None
            self._capturando_etiqueta = False

    def handle_data(self, data):
        if self._actual is None:
            return
        if self._capturando_etiqueta:
            self._actual['etiqueta'] += data
        if self._actual.get('_capturando_valor'):
            self._actual['valor'] += data


class PlanesMejoramientoWebTestCase(unittest.TestCase):
    def setUp(self):
        self.uploads = tempfile.TemporaryDirectory()
        self.app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_ENGINE_OPTIONS': {},
            'UPLOAD_FOLDER': self.uploads.name,
            'WTF_CSRF_ENABLED': False,
            'RATELIMIT_ENABLED': False,
        })
        self.contexto = self.app.app_context()
        self.contexto.push()
        db.create_all()

        self.instructor = Instructor(
            nombre='Instructor Planes', correo='planes@sena.edu.co', rol='admin'
        )
        self.instructor.set_password('clave-segura')
        db.session.add(self.instructor)
        db.session.flush()
        self.ficha = Ficha(
            codigo='7000001', codigo_ficha='7000001',
            nombre_programa='ADSO', instructor_id=self.instructor.id,
            fecha_inicio=date.today() - timedelta(days=10),
            fecha_fin=date.today() + timedelta(days=300),
        )
        db.session.add(self.ficha)
        db.session.flush()
        db.session.add_all([
            ConfiguracionAlertas(ficha_id=self.ficha.id),
            ConfiguracionAlertasComite(ficha_id=self.ficha.id),
            ConfiguracionAseo(ficha_id=self.ficha.id),
            ConfiguracionRanking(ficha_id=self.ficha.id),
        ])
        self.aprendiz = Aprendiz(
            documento='7000001', nombre='Ana', apellidos='Plan', ficha_id=self.ficha.id
        )
        db.session.add(self.aprendiz)
        db.session.commit()
        self.plan = PlanMejoramiento(
            aprendiz_id=self.aprendiz.id,
            ficha_id=self.ficha.id,
            creado_por=self.instructor.id,
            actividades='Entregar la reflexión y participar en la asesoría.',
            fecha_limite=datetime.utcnow() + timedelta(days=10),
        )
        db.session.add(self.plan)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.contexto.pop()
        self.uploads.cleanup()

    def _aprendiz_cliente(self):
        cliente = self.app.test_client()
        cliente.post(f'/aprendiz/{self.ficha.id}', data={'documento': self.aprendiz.documento})
        return cliente

    def _instructor_cliente(self):
        cliente = self.app.test_client()
        g.pop('_login_user', None)
        with cliente.session_transaction() as sesion:
            sesion['_user_id'] = str(self.instructor.id)
            sesion['_fresh'] = True
        return cliente

    def _crear_tarea(self, titulo, fecha_limite, creada_en=None):
        tarea = Tarea(
            ficha_id=self.ficha.id,
            instructor_id=self.instructor.id,
            titulo=titulo,
            descripcion='Actividad de prueba para el panel del aprendiz.',
            fecha_limite=fecha_limite,
            requiere_archivo=False,
        )
        if creada_en is not None:
            tarea.creada_en = creada_en
        db.session.add(tarea)
        db.session.commit()
        return tarea

    def _tarjeta_tarea(self, tarea):
        respuesta = self._aprendiz_cliente().get(f'/aprendiz/{self.ficha.id}/panel')
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn(b'aria-label="Evidencias entregadas"', respuesta.data)
        parser = _TarjetasTareaParser()
        parser.feed(respuesta.get_data(as_text=True))
        tarjetas = [
            tarjeta for tarjeta in parser.tarjetas
            if tarjeta['atributos'].get('data-task-title') == tarea.titulo.lower()
        ]
        self.assertEqual(len(tarjetas), 1, f'Debe mostrarse una tarjeta para {tarea.titulo}')
        return tarjetas[0]

    @staticmethod
    def _clases(elemento):
        return set(elemento.get('class', '').split())

    def _barra_tiempo(self, tarjeta):
        barras = [
            atributos for _, atributos in tarjeta['elementos']
            if 'task-deadline-meter' in self._clases(atributos)
        ]
        self.assertEqual(len(barras), 1, 'La tarea debe mostrar una barra de tiempo')
        barra = barras[0]
        self.assertEqual(barra.get('role'), 'progressbar')
        self.assertIn('aria-label', barra)
        porcentaje = int(barra['aria-valuenow'])
        self.assertGreaterEqual(porcentaje, 0)
        self.assertLessEqual(porcentaje, 100)
        return barra, porcentaje

    def test_aprendiz_ve_el_plan_y_puede_enviar_evidencia(self):
        cliente = self._aprendiz_cliente()
        panel = cliente.get(f'/aprendiz/{self.ficha.id}/panel')
        self.assertEqual(panel.status_code, 200)
        self.assertIn(b'Mis planes de mejoramiento', panel.data)
        self.assertIn(self.plan.actividades.encode(), panel.data)

        respuesta = cliente.post(
            f'/aprendiz/{self.ficha.id}/subir-evidencia-plan/{self.plan.id}',
            data={
                'archivo_evidencia_plan': (
                    BytesIO(b'%PDF-1.4\n evidencia del plan\n%%EOF'),
                    'cumplimiento.pdf',
                ),
                'observaciones_aprendiz': 'Realicé las dos actividades acordadas.',
            },
            content_type='multipart/form-data',
        )
        self.assertEqual(respuesta.status_code, 302)
        db.session.refresh(self.plan)
        self.assertTrue(self.plan.evidencia_url)
        self.assertTrue(os.path.isfile(os.path.join(self.uploads.name, self.plan.evidencia_url)))
        descarga = cliente.get(f'/aprendiz/descargar-evidencia-plan/{self.plan.id}')
        self.assertEqual(descarga.status_code, 200)
        self.assertTrue(descarga.data.startswith(b'%PDF'))
        descarga.close()

    def test_formulario_de_evidencia_expone_ayudas_accesibles_y_formatos(self):
        cliente = self._aprendiz_cliente()
        panel = cliente.get(f'/aprendiz/{self.ficha.id}/panel')
        self.assertEqual(panel.status_code, 200)

        archivo_ayuda = f'plan-evidencia-ayuda-{self.plan.id}'.encode()
        nota_ayuda = f'plan-nota-ayuda-{self.plan.id}'.encode()
        self.assertIn(
            f'aria-describedby="{archivo_ayuda.decode()}"'.encode(), panel.data
        )
        self.assertIn(f'id="{archivo_ayuda.decode()}"'.encode(), panel.data)
        self.assertIn(
            f'<label for="plan-evidencia-{self.plan.id}">Archivo de evidencia'.encode(),
            panel.data,
        )
        self.assertIn(
            f'aria-describedby="{nota_ayuda.decode()}"'.encode(), panel.data
        )
        self.assertIn(f'id="{nota_ayuda.decode()}"'.encode(), panel.data)
        self.assertIn(
            f'<label for="plan-nota-{self.plan.id}">Nota para tu instructor'.encode(),
            panel.data,
        )

        def texto_ayuda(ayuda_id):
            inicio = panel.data.index(f'id="{ayuda_id.decode()}"'.encode())
            inicio_texto = panel.data.index(b'>', inicio) + 1
            fin_texto = panel.data.index(b'<', inicio_texto)
            return panel.data[inicio_texto:fin_texto]

        ayuda_archivo = texto_ayuda(archivo_ayuda)
        ayuda_nota = texto_ayuda(nota_ayuda)
        self.assertIn('Formatos admitidos:'.encode(), ayuda_archivo)
        self.assertIn('comentario breve'.encode(), ayuda_nota)

        for formato in (b'PDF', b'PNG', b'JPG', b'JPEG', b'ZIP', b'RAR', b'DOC', b'DOCX'):
            with self.subTest(formato=formato.decode()):
                self.assertIn(formato, ayuda_archivo)

    def test_planes_pendientes_y_vencidos_anuncian_su_estado(self):
        cliente = self._aprendiz_cliente()

        pendiente = cliente.get(f'/aprendiz/{self.ficha.id}/panel')
        self.assertEqual(pendiente.status_code, 200)
        inicio_tarjeta = pendiente.data.index(b'<article class="learner-plan-item')
        fin_tarjeta = pendiente.data.index(b'</article>', inicio_tarjeta) + len(b'</article>')
        tarjeta_pendiente = pendiente.data[inicio_tarjeta:fin_tarjeta]
        self.assertIn(b'role="status"', tarjeta_pendiente)
        self.assertIn('Pendiente'.encode(), tarjeta_pendiente)
        self.assertIn('Evidencia pendiente'.encode(), tarjeta_pendiente)
        self.assertIn('Aún no has enviado evidencia'.encode(), tarjeta_pendiente)

        self.plan.estado = 'vencido'
        self.plan.fecha_limite = datetime.utcnow() - timedelta(days=1)
        db.session.commit()
        vencido = cliente.get(f'/aprendiz/{self.ficha.id}/panel')
        self.assertEqual(vencido.status_code, 200)
        inicio_tarjeta = vencido.data.index(b'<article class="learner-plan-item')
        fin_tarjeta = vencido.data.index(b'</article>', inicio_tarjeta) + len(b'</article>')
        tarjeta_vencida = vencido.data[inicio_tarjeta:fin_tarjeta]
        self.assertIn(b'role="status"', tarjeta_vencida)
        self.assertIn('Vencido'.encode(), tarjeta_vencida)
        self.assertIn('La fecha límite ya pasó'.encode(), tarjeta_vencida)
        self.assertIn('Habla con tu instructor'.encode(), tarjeta_vencida)

    def test_tarea_con_fecha_muestra_barra_accesible_porcentaje_y_tiempo_restante(self):
        ahora = datetime.utcnow()
        tarea = self._crear_tarea(
            'Taller con seguimiento de tiempo',
            ahora + timedelta(days=5),
            creada_en=ahora - timedelta(days=5),
        )

        tarjeta = self._tarjeta_tarea(tarea)
        barra, porcentaje = self._barra_tiempo(tarjeta)
        self.assertGreater(porcentaje, 25)
        self.assertLess(porcentaje, 75)
        texto = ' '.join(tarjeta['texto'])
        self.assertRegex(texto, re.compile(r'\b\d{1,3}\s*%'))
        self.assertIn('Quedan ', texto)
        self.assertTrue(any('is-normal' in self._clases(attrs)
                            for _, attrs in tarjeta['elementos'])
                        or 'is-normal' in self._clases(tarjeta['atributos']))
        self.assertTrue(barra['aria-label'].strip())

    def test_prorroga_define_fecha_limite_efectiva_y_evitar_alerta_vencida(self):
        ahora = datetime.utcnow()
        limite_original = ahora - timedelta(days=2)
        limite_prorrogado = ahora + timedelta(days=8)
        tarea = self._crear_tarea(
            'Tarea con prórroga vigente', limite_original,
            creada_en=ahora - timedelta(days=8),
        )
        db.session.add(ProrrogaTarea(
            tarea_id=tarea.id,
            aprendiz_id=self.aprendiz.id,
            instructor_id=self.instructor.id,
            nueva_fecha_limite=limite_prorrogado,
            motivo='Ampliación acordada para completar la actividad.',
        ))
        db.session.commit()

        tarjeta = self._tarjeta_tarea(tarea)
        self._barra_tiempo(tarjeta)
        texto = ' '.join(' '.join(tarjeta['texto']).split())
        self.assertIn(f'Límite: {limite_prorrogado.strftime("%d/%m/%Y %H:%M")}', texto)
        self.assertNotIn(f'Límite: {limite_original.strftime("%d/%m/%Y %H:%M")}', texto)
        self.assertNotIn('Entrega extemporánea permitida', texto)
        self.assertNotIn('Justificación o motivo de la entrega extemporánea', texto)
        self.assertNotIn('Enviar evidencia extemporánea', texto)
        alertas_vencidas = [
            attrs for _, attrs in tarjeta['elementos']
            if 'task-alert' in self._clases(attrs)
            and 'is-overdue' in self._clases(attrs)
        ]
        self.assertEqual(alertas_vencidas, [])

    def test_tarea_sin_fecha_no_muestra_barra_ni_cuenta_regresiva(self):
        pendiente = self._crear_tarea('Actividad pendiente sin fecha límite', None)
        entregada = self._crear_tarea('Actividad entregada sin fecha límite', None)
        db.session.add(Entrega(
            tarea_id=entregada.id,
            aprendiz_id=self.aprendiz.id,
            fecha_entrega=datetime.utcnow(),
            estado_revision='pendiente',
        ))
        db.session.commit()

        for tarea in (pendiente, entregada):
            with self.subTest(tarea=tarea.titulo):
                tarjeta = self._tarjeta_tarea(tarea)
                texto = ' '.join(tarjeta['texto'])
                barras = [
                    attrs for _, attrs in tarjeta['elementos']
                    if 'task-deadline-meter' in self._clases(attrs)
                ]
                self.assertEqual(barras, [])
                self.assertNotIn('Quedan ', texto)
                self.assertNotIn('Plazo vencido', texto)

    def test_tarea_urgente_y_vencida_muestran_alertas_con_estado_claro(self):
        ahora = datetime.utcnow()
        urgente = self._crear_tarea(
            'Tarea urgente', ahora + timedelta(hours=3),
            creada_en=ahora - timedelta(days=3),
        )
        vencida = self._crear_tarea(
            'Tarea vencida', ahora - timedelta(days=2),
            creada_en=ahora - timedelta(days=7),
        )

        for tarea, estado, texto_esperado in (
            (urgente, 'is-urgent', 'Quedan '),
            (vencida, 'is-overdue', 'Plazo vencido'),
        ):
            with self.subTest(tarea=tarea.titulo):
                tarjeta = self._tarjeta_tarea(tarea)
                elementos = [tarjeta['atributos']] + [
                    attrs for _, attrs in tarjeta['elementos']
                ]
                self.assertTrue(any(estado in self._clases(attrs) for attrs in elementos))
                alertas = [
                    attrs for _, attrs in tarjeta['elementos']
                    if 'task-alert' in self._clases(attrs)
                ]
                self.assertTrue(alertas, 'El vencimiento debe mostrarse como aviso destacado')
                self.assertIn(texto_esperado, ' '.join(tarjeta['texto']))

    def test_tarea_proxima_y_evidencia_entregada_muestran_estado_y_progreso_coherentes(self):
        ahora = datetime.utcnow()
        proxima = self._crear_tarea(
            'Tarea próxima', ahora + timedelta(days=2),
            creada_en=ahora - timedelta(days=1),
        )
        minutos = self._crear_tarea(
            'Tarea con menos de una hora', ahora + timedelta(minutes=20),
            creada_en=ahora - timedelta(days=2),
        )
        entregada = self._crear_tarea(
            'Evidencia enviada a tiempo', ahora + timedelta(days=2),
            creada_en=ahora - timedelta(days=1),
        )
        db.session.add(Entrega(
            tarea_id=entregada.id,
            aprendiz_id=self.aprendiz.id,
            fecha_entrega=ahora,
            estado_revision='pendiente',
        ))
        db.session.commit()

        tarjeta_proxima = self._tarjeta_tarea(proxima)
        barra_proxima, _ = self._barra_tiempo(tarjeta_proxima)
        self.assertIn('is-soon', self._clases(barra_proxima))
        self.assertIn('Tu plazo se acerca', ' '.join(tarjeta_proxima['texto']))

        tarjeta_minutos = self._tarjeta_tarea(minutos)
        barra_minutos, _ = self._barra_tiempo(tarjeta_minutos)
        self.assertIn('is-urgent', self._clases(barra_minutos))
        self.assertRegex(' '.join(tarjeta_minutos['texto']), r'Quedan \d+ minutos')

        tarjeta_entregada = self._tarjeta_tarea(entregada)
        barra_entregada, porcentaje = self._barra_tiempo(tarjeta_entregada)
        self.assertEqual(porcentaje, 100)
        self.assertIn('is-complete', self._clases(barra_entregada))
        self.assertIn('Evidencia entregada', ' '.join(tarjeta_entregada['texto']))

    def test_formulario_de_inasistencia_guia_el_soporte_o_nota(self):
        sesion = SesionAsistencia(
            ficha_id=self.ficha.id,
            fecha=date.today() - timedelta(days=2),
        )
        db.session.add(sesion)
        db.session.flush()
        registro = RegistroAsistencia(
            sesion_id=sesion.id,
            aprendiz_id=self.aprendiz.id,
            estado='FALTA',
        )
        db.session.add(registro)
        db.session.commit()

        cliente = self._aprendiz_cliente()
        panel = cliente.get(f'/aprendiz/{self.ficha.id}/panel')
        self.assertEqual(panel.status_code, 200)

        soporte_id = f'soporte-inasistencia-{registro.id}'
        nota_id = f'nota-inasistencia-{registro.id}'
        guia_id = f'guia-inasistencia-{registro.id}'
        formatos_id = f'formatos-inasistencia-{registro.id}'
        self.assertIn(f'<label for="{soporte_id}">Soporte'.encode(), panel.data)
        self.assertIn(f'<label for="{nota_id}">Nota'.encode(), panel.data)
        self.assertIn(f'aria-describedby="{guia_id} {formatos_id}"'.encode(), panel.data)
        self.assertIn(f'aria-describedby="{guia_id}"'.encode(), panel.data)
        self.assertIn(f'id="{guia_id}"'.encode(), panel.data)
        self.assertIn('al menos una opción'.encode(), panel.data)
        self.assertIn(f'id="{formatos_id}"'.encode(), panel.data)
        self.assertIn('Formatos admitidos: PDF, PNG, JPG/JPEG, DOC y DOCX.'.encode(), panel.data)

    def test_turnos_del_aprendiz_tienen_un_solo_formulario_con_csrf_y_completan_el_flujo(self):
        cliente = self._aprendiz_cliente()
        self.app.config['WTF_CSRF_ENABLED'] = True

        panel = cliente.get(f'/aprendiz/{self.ficha.id}/panel')
        self.assertEqual(panel.status_code, 200)
        parser = _FormulariosParser()
        parser.feed(panel.get_data(as_text=True))
        url_pedir = f'/aprendiz/{self.ficha.id}/pedir-turno'
        formularios_pedir = [
            formulario for formulario in parser.formularios
            if formulario['atributos'].get('action') == url_pedir
        ]
        self.assertEqual(len(formularios_pedir), 1)
        token_pedir = formularios_pedir[0]['campos'].get('csrf_token')
        self.assertTrue(token_pedir, 'El formulario debe enviar el token CSRF que genera la sesión.')

        solicitud = cliente.post(
            url_pedir,
            data={'csrf_token': token_pedir, 'motivo': 'Revisar mi proyecto'},
        )
        self.assertEqual(solicitud.status_code, 302)
        turno = TurnoAtencion.query.filter_by(
            ficha_id=self.ficha.id,
            aprendiz_id=self.aprendiz.id,
        ).one()
        self.assertEqual(turno.estado, 'esperando')
        self.assertEqual(turno.motivo, 'Revisar mi proyecto')

        solicitud_duplicada = cliente.post(
            url_pedir,
            data={'csrf_token': token_pedir, 'motivo': 'Otro motivo'},
            follow_redirects=True,
        )
        self.assertEqual(solicitud_duplicada.status_code, 200)
        self.assertIn(
            'Ya tienes un turno en la fila o el instructor te está atendiendo.'.encode(),
            solicitud_duplicada.data,
        )
        self.assertEqual(TurnoAtencion.query.filter_by(ficha_id=self.ficha.id).count(), 1)
        self.assertEqual(turno.motivo, 'Revisar mi proyecto')

        panel_en_fila = cliente.get(f'/aprendiz/{self.ficha.id}/panel')
        self.assertIn('Estás en la fila'.encode(), panel_en_fila.data)
        parser = _FormulariosParser()
        parser.feed(panel_en_fila.get_data(as_text=True))
        url_cancelar = f'/aprendiz/{self.ficha.id}/cancelar-turno'
        formularios_cancelar = [
            formulario for formulario in parser.formularios
            if formulario['atributos'].get('action') == url_cancelar
        ]
        self.assertEqual(len(formularios_cancelar), 1)
        token_cancelar = formularios_cancelar[0]['campos'].get('csrf_token')
        self.assertTrue(token_cancelar)

        cancelacion = cliente.post(
            url_cancelar,
            data={'csrf_token': token_cancelar},
        )
        self.assertEqual(cancelacion.status_code, 302)
        db.session.refresh(turno)
        self.assertEqual(turno.estado, 'cancelado')
        self.assertIsNotNone(turno.completado_en)

        panel_final = cliente.get(f'/aprendiz/{self.ficha.id}/panel')
        self.assertIn(b'Pedir Turno', panel_final.data)

    def test_post_de_turno_sin_csrf_no_crea_turno_y_vuelve_al_panel(self):
        cliente = self._aprendiz_cliente()
        self.app.config['WTF_CSRF_ENABLED'] = True

        respuesta = cliente.post(
            f'/aprendiz/{self.ficha.id}/pedir-turno',
            data={'motivo': 'Consulta'},
        )

        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(
            respuesta.headers['Location'],
            f'/aprendiz/{self.ficha.id}/panel',
        )
        self.assertEqual(TurnoAtencion.query.filter_by(ficha_id=self.ficha.id).count(), 0)
        panel = cliente.get(respuesta.headers['Location'])
        self.assertIn('La sesión del formulario expiró'.encode(), panel.data)

    def test_barras_de_progreso_anuncian_la_metrica_y_el_porcentaje_correctos(self):
        self._crear_tarea('Evidencia por entregar', datetime.utcnow() + timedelta(days=3))
        sesion = SesionAsistencia(ficha_id=self.ficha.id, fecha=date.today())
        db.session.add(sesion)
        db.session.flush()
        db.session.add(RegistroAsistencia(
            sesion_id=sesion.id,
            aprendiz_id=self.aprendiz.id,
            estado='ASISTE',
        ))
        db.session.commit()

        panel = self._aprendiz_cliente().get(f'/aprendiz/{self.ficha.id}/panel')
        self.assertEqual(panel.status_code, 200)
        parser = _TarjetasProgresoParser()
        parser.feed(panel.get_data(as_text=True))
        tarjetas = {
            tarjeta['etiqueta'].strip(): tarjeta
            for tarjeta in parser.tarjetas
        }

        for metrica, nombre_aria, valor, texto in (
            ('📅 Asistencia', 'Asistencia', '100', '1 de 1 sesiones'),
            ('📋 Evidencias', 'Evidencias entregadas', '0', '0 de 1 evidencias entregadas'),
        ):
            with self.subTest(metrica=metrica):
                tarjeta = tarjetas[metrica]
                barra = tarjeta['barra']
                self.assertEqual(barra.get('role'), 'progressbar')
                self.assertEqual(barra.get('aria-label'), nombre_aria)
                self.assertEqual(barra.get('aria-valuenow'), valor)
                self.assertIn(texto, barra.get('aria-valuetext', ''))

    def test_instructor_no_puede_cerrar_sin_evidencia_y_luego_puede_revisarla(self):
        cliente = self._instructor_cliente()
        bloqueado = cliente.post(
            f'/instructor/fichas/{self.ficha.id}/planes/{self.plan.id}/cumplir',
            follow_redirects=True,
        )
        self.assertIn('aún no ha enviado evidencia'.encode(), bloqueado.data)
        db.session.refresh(self.plan)
        self.assertEqual(self.plan.estado, 'pendiente')

        aprendiz_cliente = self._aprendiz_cliente()
        aprendiz_cliente.post(
            f'/aprendiz/{self.ficha.id}/subir-evidencia-plan/{self.plan.id}',
            data={
                'archivo_evidencia_plan': (
                    BytesIO(b'%PDF-1.4\n evidencia revisable\n%%EOF'),
                    'revisable.pdf',
                ),
            },
            content_type='multipart/form-data',
        )
        db.session.refresh(self.plan)
        pagina = cliente.get(f'/instructor/fichas/{self.ficha.id}/planes-mejoramiento')
        self.assertEqual(pagina.status_code, 200)
        self.assertIn(b'Evidencia del aprendiz', pagina.data)
        descarga = cliente.get(f'/instructor/planes/{self.plan.id}/evidencia')
        self.assertEqual(descarga.status_code, 200)
        self.assertTrue(descarga.data.startswith(b'%PDF'))
        descarga.close()
        cerrado = cliente.post(
            f'/instructor/fichas/{self.ficha.id}/planes/{self.plan.id}/cumplir',
            data={'observaciones_instructor': 'Evidencia revisada.'},
        )
        self.assertEqual(cerrado.status_code, 302)
        db.session.refresh(self.plan)
        self.assertEqual(self.plan.estado, 'cumplido')
        self.assertEqual(self.plan.observaciones_instructor, 'Evidencia revisada.')


if __name__ == '__main__':
    unittest.main()
