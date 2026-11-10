# Auditoría funcional y normativa — noviembre de 2026

**Alcance:** se revisó y corrigió el algoritmo de turnos de aseo. Además, se leyó toda la aplicación y se contrastó con el Acuerdo 009 de 2024 (reglamento del aprendiz SENA), el debido proceso y la Ley 1581 de 2012.

**Método:** la revisión se hizo leyendo el código. Cada hallazgo se corrigió con su prueba automatizada. Los artículos citados salen del catálogo `FUNDAMENTOS` de `app/services/normativa_sena.py` y no se compararon con el texto del PDF que está en `app/normativa/`. Las rutas son relativas a la raíz del proyecto.

**Estado al 9 de noviembre de 2026:** todos los hallazgos están corregidos. Donde el reglamento dejaba margen, la columna «Decisión aplicada» indica qué se resolvió y quién lo decidió.

## 1. Turnos de aseo

El usuario confirmó este orden de elección:
1. **Descanso:** nadie repite en sesiones seguidas si hay alternativa.
2. **Menor carga total:** turnos cumplidos más programados.
3. Menos turnos cumplidos.
4. Enfriamiento y rotación de parejas.
5. Antigüedad.
6. Sorteo.

Se usa la carga total, y no solo los cumplidos, porque al planear un mes los cumplidos no cambian y la misma persona recibiría todos los cupos.

| # | Hallazgo | Archivo | Corrección |
|---|---|---|---|
| A1 | En un «no cumplido» parcial, quien sí cumplió no sumaba el turno. | `app/services/aseo.py` | Ahora cuenta a quien quedó marcado como cumplidor. |
| A2 | Un turno manual ya `no_cumplido` seguía sumando carga en el motor. | `app/services/aseo_motor_puro.py` | Solo suman los turnos pendientes. |
| A3 | Las suplencias podían elegir a quien hizo aseo en la sesión anterior. | `app/services/aseo.py` | El suplente respeta el descanso. |
| A4 | La explicación al aprendiz decía que el descanso «se procura». | `app/services/aseo_cola.py` | Dice que el descanso es obligatorio mientras haya alternativa. |
| A5 | El resumen de aseo fallaba para aprendices sin contador (condicionados o en solo lectura). | `app/services/aseo.py` (`resumen_aprendiz`) | Usa un contador vacío. |

Pruebas: `tests/test_aseo_auditoria_equidad.py`. Incluye una prueba sobre 50 calendarios aleatorios que verifica dos cosas:
- Entre quienes descansaron, el turno va siempre a la menor carga.
- Sin ausencias, la diferencia entre la mayor y la menor carga nunca supera 1.

## 2. Debido proceso, asistencia y comité

| # | Hallazgo | Decisión aplicada |
|---|---|---|
| B1 | Una alerta con más de 15 días pasaba sola a comité. | **Usuario:** solo recordar. El sistema avisa al instructor una vez por caso y él decide si lo remite con su informe (Art. 51, num. 1). |
| B2 | Una `FALTA` contaba como injustificada desde el mismo día. | Solo cuenta cuando vence el plazo para justificarla (Art. 28, par. 3). |
| B3 | El porcentaje de asistencia generaba un caso de comité en rojo y lo llamaba «mínimo reglamentario». | Ahora es un aviso preventivo amarillo de tipo `asistencia`, que aclara que el Acuerdo no fija un mínimo. |
| B4 | Las excusas restaban en el porcentaje de asistencia del aprendiz. | Solo resta la `FALTA`. Aplica a las recomendaciones y al panel del aprendiz. |
| B5 | La regla de 5 faltas en 90 días repetía la de todo el proceso y usaba `date.today()`. | Se eliminó la regla de ventana y se retiraron sus campos de la configuración. |
| B6 | No estaba claro qué significa «tres días continuos». | Se cuentan sesiones de formación programadas seguidas: un día sin sesión no corta ni suma la racha. Quedó documentado en el código. |
| B7 | Se vencían planes que ya tenían evidencia enviada; el texto hablaba de «auto-escalación». | Un plan con evidencia espera la revisión del instructor. El texto dice que el instructor decide. |
| B8 | `crear_plan_mejoramiento` no validaba el tope de 20 días. | El servicio valida y rechaza el plan; la ruta muestra el error y las advertencias. |
| B9 | Los planes se contaban por etapa, pero los llamados se registran por fase. | `PlanMejoramiento.fase` es una columna nueva. Llamados y planes se cuentan por fase. |
| B10 | Los llamados no tenían descargos, notificación ni anulación. | El aprendiz recibe aviso y escribe sus descargos desde el panel. El instructor anula con motivo: el llamado anulado queda en el expediente, pero no cuenta para el tope. La fecha no puede ser futura. |
| B11 | Se recomendaba la cancelación al año aunque hubiera un aplazamiento vigente. | No se recomienda mientras el aplazamiento siga vigente, y el año se corre por los días aplazados. El rótulo dice «Recomendación». |
| B12 | El instructor podía autorizar una ampliación y cambiar cualquier estado sin dejar rastro. | La ampliación exige el número de acta del comité. Una novedad solicitada solo pasa a autorizada o negada, y cada cambio guarda quién lo hizo y cuándo. |
| B13 | Un reintegro tardío borraba la alerta del Art. 30, num. 3. | La alerta sigue abierta como «reintegro tardío» para que decida el comité. |
| B14 | El tooltip del calendario no mostraba la causal. | Lee `causal_justificacion` y la fecha en formato dd/mm/aaaa. |
| B15 | Un estado de asistencia desconocido contaba como `FALTA`. | Cuenta como «Sin registro». |
| B16 | El expediente rotulaba toda falta como «académica» y corría los plazos desde hoy. | Rotula por causal: deserción (Art. 30), académica o disciplinaria. Los plazos se cuentan desde la fecha de remisión. |
| B17 | El plazo de justificación podía bajar de 5 días. | El mínimo es 5 en el formulario, en el cálculo y en la migración de datos. |
| B18 | Un caso escalado se podía cerrar sin acta. | El cierre exige el número del acta del comité. |

Hallazgo nuevo, corregido: las reglas usaban la fecha UTC, así que desde las 7 p. m. de Colombia el sistema ya contaba el día siguiente. `fecha_colombia` aplica UTC−5 en las alertas, en la etapa productiva, en los reintegros y en el cierre lectivo.

## 3. Acceso, datos personales y reportes

| # | Hallazgo | Decisión aplicada |
|---|---|---|
| C1–C5 | El documento por URL o por formulario permitía suplantar a un aprendiz y descargar sus datos. | Corregido el 9 de noviembre: la identidad sale solo de la sesión de la misma ficha. Las URL guardadas en notificaciones se limpian en la migración `y49`. |
| C6 | El ranking restaba por llamados y alertas, y mostraba los últimos puestos. | **Usuario:** sin castigos y discreto. No hay restas disciplinarias. El aprendiz ve el podio y su propia fila, y el instructor ya no ve la insignia «Alerta activa» en la tabla. |
| C7 | Importar el reporte de una ficha ajena vinculaba sin permiso. | **Usuario:** se acepta el reporte oficial. Se vincula como colaborador, pero solo se agregan aprendices y juicios nuevos, sin sobrescribir datos. |
| C8 | Aprendices cancelados, trasladados o retirados seguían subiendo archivos. | **Usuario:** solo lectura. Pueden consultar y descargar su reporte. Los POST se bloquean con un aviso, en el panel y en el aseo. |
| C9 | El ranking excluía a los condicionados. | Usa el mismo universo que el llamado a lista. |
| C10 | El ranking por periodo restaba planes y alertas de cualquier fecha. | Planes y alertas se filtran por el periodo. |
| C11 | La tendencia mezclaba instantáneas de cortes distintos. | Sin corte, la tendencia compara solo con el ranking general. |
| C12 | El panel recalculaba el ranking, vencía planes de todas las fichas y fallaba con error 500 si caían las alertas. | El panel solo lee el ranking y vence los planes de su ficha. Si fallan las alertas, se muestra igual. |
| C13 | El cierre ignoraba a aprendices sin juicios. | Compara contra todos los resultados de la ficha. |
| C14 | El mensaje de cierre citaba la planeación productiva aunque no aplicara. | Solo la menciona si falta. |
| C15 | El cierre podía resolver alertas de aprendices no evaluados. | Solo resuelve las de quienes evaluó. |
| C16 | El reporte de coordinación contaba llamados anulados y aplazamientos ya reintegrados. | Cuenta solo los vigentes y excluye los reintegros a tiempo. Conserva la cédula porque la coordinación la necesita. |
| C17 | Los exportes de ranking e insignias incluían la cédula. | Ya no la incluyen. |

Hallazgo nuevo, corregido: al guardar los enlaces del portafolio con un formato inválido, tanto en el panel del aprendiz como en el del instructor, el formulario normal usaba una variable que ya no existía (`str(e)`) y fallaba con error 500. Ahora muestra el mensaje del validador, que indica qué enlace corregir.

## Migración

`migrations/versions/y49_auditoria_sena.py` hace tres cosas:
- Agrega descargos y anulación a los llamados, la fase a los planes, y el acta y el rastro de cambios a las novedades.
- Sube a 5 los plazos de justificación menores.
- Quita `?documento=` de las URL de las notificaciones.

Se validó en modo offline (`flask db upgrade --sql` y su downgrade).

## Pruebas

- `tests/test_auditoria_sena.py`: una prueba o más por cada corrección de B y C.
- Pruebas ajustadas porque fijaban el comportamiento anterior: `test_alertas.py`, `test_comite_productiva.py`, `test_novedades.py`, `test_debido_proceso.py`, `test_cierre_y_reporte.py`, `test_importacion_ficha.py` y `test_migration_heads.py`.
