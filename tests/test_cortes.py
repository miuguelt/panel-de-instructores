from datetime import date

from app import db
from app.models import Corte, FichaInstructor, SesionAsistencia, Tarea
from tests.test_flujos_web import FlujosWebTestCase


class CortesWebTestCase(FlujosWebTestCase):
    def _crear_corte(self, nombre, compartido=True):
        datos = {
            'nombre_corte': nombre,
        }
        if compartido:
            datos['compartido'] = 'on'
        respuesta = self.cliente.post(
            f'/instructor/fichas/{self.ficha.id}/ranking/nuevo-corte',
            data=datos,
        )
        self.assertEqual(respuesta.status_code, 302)
        return Corte.query.filter_by(
            ficha_id=self.ficha.id,
            nombre=nombre,
        ).one()

    def test_cada_instructor_crea_cortes_separados_y_comparte_el_corte_explicito(self):
        corte_principal = self._crear_corte('Corte principal')
        self.cliente.post(
            f'/instructor/fichas/{self.ficha.id}/tareas',
            data={
                'corte_id': corte_principal.id,
                'titulo': 'Tarea del corte principal',
            },
        )
        self.cliente.post(
            f'/instructor/fichas/{self.ficha.id}/asistencia',
            data={
                'corte_id': corte_principal.id,
                'fecha': '2030-01-10',
                f'asistencia_{self.aprendiz.id}': 'ASISTE',
                f'asistencia_{self.otro_aprendiz.id}': 'FALTA',
            },
        )

        db.session.add(FichaInstructor(
            ficha_id=self.ficha.id,
            instructor_id=self.ajeno.id,
        ))
        db.session.commit()
        self._autenticar(self.ajeno)
        corte_ajeno = self._crear_corte('Corte del colaborador')
        self.cliente.post(
            f'/instructor/fichas/{self.ficha.id}/tareas',
            data={
                'corte_id': corte_ajeno.id,
                'titulo': 'Tarea del corte del colaborador',
            },
        )

        self.assertNotEqual(corte_principal.id, corte_ajeno.id)
        self.assertEqual(
            Tarea.query.filter_by(corte_id=corte_principal.id).count(),
            1,
        )
        self.assertEqual(
            Tarea.query.filter_by(corte_id=corte_ajeno.id).count(),
            1,
        )
        self.assertEqual(
            SesionAsistencia.query.filter_by(corte_id=corte_principal.id).count(),
            1,
        )

        visible = self.cliente.get(
            f'/instructor/fichas/{self.ficha.id}/tareas?corte_id={corte_principal.id}'
        )
        self.assertEqual(visible.status_code, 200)
        self.assertIn(b'Tarea del corte principal', visible.data)
        self.assertNotIn(b'Actividad de prueba', visible.data)

        self._autenticar(self.instructor)
        compartido = self.cliente.get(
            f'/instructor/fichas/{self.ficha.id}/tareas?corte_id={corte_ajeno.id}'
        )
        self.assertEqual(compartido.status_code, 200)
        self.assertIn(b'Tarea del corte del colaborador', compartido.data)

        self._autenticar(self.ajeno)
        asistencia_compartida = self.cliente.get(
            f'/instructor/fichas/{self.ficha.id}/asistencia?corte_id={corte_principal.id}'
        )
        self.assertEqual(asistencia_compartida.status_code, 200)
        self.assertIn(b'10/01/2030', asistencia_compartida.data)

    def test_corte_privado_no_se_expone_a_otro_instructor(self):
        self.instructor.rol = 'colaborador'
        db.session.commit()
        corte_privado = self._crear_corte('Corte privado', compartido=False)
        db.session.add(FichaInstructor(
            ficha_id=self.ficha.id,
            instructor_id=self.ajeno.id,
        ))
        db.session.commit()

        self._autenticar(self.ajeno)
        with self.cliente as cliente:
            respuesta = cliente.get(
                f'/instructor/fichas/{self.ficha.id}/tareas?corte_id={corte_privado.id}'
            )
        self.assertEqual(respuesta.status_code, 302)

    def test_corte_cerrado_se_consulta_pero_no_admite_nuevos_registros(self):
        corte = self._crear_corte('Corte para cerrar')

        respuesta = self.cliente.post(
            f'/instructor/fichas/{self.ficha.id}/ranking/cortes/{corte.id}/estado',
            data={'estado': 'cerrado'},
        )
        self.assertEqual(respuesta.status_code, 302)
        db.session.refresh(corte)
        self.assertEqual(corte.estado, Corte.ESTADO_CERRADO)
        self.assertIsNotNone(corte.fecha_fin)

        tareas_antes = Tarea.query.filter_by(corte_id=corte.id).count()
        sesiones_antes = SesionAsistencia.query.filter_by(corte_id=corte.id).count()
        crear_tarea = self.cliente.post(
            f'/instructor/fichas/{self.ficha.id}/tareas',
            data={
                'corte_id': corte.id,
                'titulo': 'No debe entrar al corte cerrado',
            },
        )
        guardar_asistencia = self.cliente.post(
            f'/instructor/fichas/{self.ficha.id}/asistencia',
            data={
                'corte_id': corte.id,
                'fecha': '2030-02-10',
                f'asistencia_{self.aprendiz.id}': 'ASISTE',
                f'asistencia_{self.otro_aprendiz.id}': 'FALTA',
            },
        )

        self.assertEqual(crear_tarea.status_code, 302)
        self.assertEqual(guardar_asistencia.status_code, 302)
        self.assertEqual(Tarea.query.filter_by(corte_id=corte.id).count(), tareas_antes)
        self.assertEqual(
            SesionAsistencia.query.filter_by(corte_id=corte.id).count(),
            sesiones_antes,
        )

        consulta = self.cliente.get(
            f'/instructor/fichas/{self.ficha.id}/ranking?corte_id={corte.id}'
        )
        self.assertEqual(consulta.status_code, 200)
        self.assertIn(b'Cerrado', consulta.data)

    def test_reactivar_corte_cierra_el_anterior_y_archivar_es_final(self):
        primer_corte = self._crear_corte('Primer corte')
        segundo_corte = self._crear_corte('Segundo corte')

        cerrar = self.cliente.post(
            f'/instructor/fichas/{self.ficha.id}/ranking/cortes/{primer_corte.id}/estado',
            data={'estado': 'cerrado'},
        )
        reactivar = self.cliente.post(
            f'/instructor/fichas/{self.ficha.id}/ranking/cortes/{primer_corte.id}/estado',
            data={'estado': 'activo'},
        )
        self.assertEqual(cerrar.status_code, 302)
        self.assertEqual(reactivar.status_code, 302)
        db.session.refresh(primer_corte)
        db.session.refresh(segundo_corte)
        self.assertEqual(primer_corte.estado, Corte.ESTADO_ACTIVO)
        self.assertEqual(segundo_corte.estado, Corte.ESTADO_CERRADO)
        self.assertIsNotNone(segundo_corte.fecha_fin)

        cerrar_de_nuevo = self.cliente.post(
            f'/instructor/fichas/{self.ficha.id}/ranking/cortes/{primer_corte.id}/estado',
            data={'estado': 'cerrado'},
        )
        archivar = self.cliente.post(
            f'/instructor/fichas/{self.ficha.id}/ranking/cortes/{primer_corte.id}/estado',
            data={'estado': 'archivado'},
        )
        reactivar_archivado = self.cliente.post(
            f'/instructor/fichas/{self.ficha.id}/ranking/cortes/{primer_corte.id}/estado',
            data={'estado': 'activo'},
        )
        self.assertEqual(cerrar_de_nuevo.status_code, 302)
        self.assertEqual(archivar.status_code, 302)
        self.assertEqual(reactivar_archivado.status_code, 302)
        db.session.refresh(primer_corte)
        self.assertEqual(primer_corte.estado, Corte.ESTADO_ARCHIVADO)

    def test_tablero_agrupado_separa_por_corte_e_instructor(self):
        corte_principal = self._crear_corte('Corte principal')
        self.cliente.post(
            f'/instructor/fichas/{self.ficha.id}/tareas',
            data={
                'corte_id': corte_principal.id,
                'titulo': 'Tarea del corte principal',
            },
        )

        db.session.add(FichaInstructor(
            ficha_id=self.ficha.id,
            instructor_id=self.ajeno.id,
        ))
        db.session.commit()
        self._autenticar(self.ajeno)
        corte_ajeno = self._crear_corte('Corte del colaborador')
        self.cliente.post(
            f'/instructor/fichas/{self.ficha.id}/tareas',
            data={
                'corte_id': corte_ajeno.id,
                'titulo': 'Tarea del corte del colaborador',
            },
        )

        self._autenticar(self.instructor)
        pagina = self.cliente.get(
            f'/instructor/fichas/{self.ficha.id}/tareas?corte_id=todos&filtro_instructor=todas'
        )
        self.assertEqual(pagina.status_code, 200)
        cuerpo = pagina.get_data(as_text=True)
        self.assertIn('tablero-agrupado', cuerpo)
        self.assertIn('Corte principal', cuerpo)
        self.assertIn('Corte del colaborador', cuerpo)
        self.assertIn('Tarea del corte principal', cuerpo)
        self.assertIn('Tarea del corte del colaborador', cuerpo)
        self.assertIn('Instructor Principal', cuerpo)
        self.assertIn('Instructor Ajeno', cuerpo)

    def test_tablero_agrupado_permite_crear_tarea_eligiendo_corte(self):
        corte_principal = self._crear_corte('Corte principal')
        pagina = self.cliente.get(
            f'/instructor/fichas/{self.ficha.id}/tareas?corte_id=todos'
        )
        self.assertEqual(pagina.status_code, 200)
        self.assertIn('Corte destino', pagina.get_data(as_text=True))

        self.cliente.post(
            f'/instructor/fichas/{self.ficha.id}/tareas',
            data={
                'corte_id': corte_principal.id,
                'titulo': 'Tarea creada desde la vista agrupada',
            },
        )
        self.assertEqual(
            Tarea.query.filter_by(
                corte_id=corte_principal.id,
                titulo='Tarea creada desde la vista agrupada',
            ).count(),
            1,
        )

        self.cliente.post(
            f'/instructor/fichas/{self.ficha.id}/tareas',
            data={
                'corte_id': 0,
                'titulo': 'Tarea sin corte asignado',
            },
        )
        self.assertEqual(
            Tarea.query.filter_by(
                corte_id=None,
                titulo='Tarea sin corte asignado',
            ).count(),
            1,
        )
