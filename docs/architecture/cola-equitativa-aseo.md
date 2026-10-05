# Prioridad de los turnos de aseo

## Problema comprobado

El calendario comparaba primero la carga total (aseos cumplidos más pendientes),
pero, ante un empate, la antigüedad o la rotación de parejas podían adelantar a
quien tenía más aseos cumplidos. La selección de suplentes ya usaba otro orden.
Las pruebas de regresión reproducen esta diferencia con registros persistidos.

## Regla de selección

Los dos cupos del turno usan los mismos criterios, en este orden:

1. Menor carga total: aseos cumplidos y turnos pendientes considerados en el cálculo.
2. Entre quienes tienen esa carga, descanso de los asignados en la sesión anterior,
   si hay otra persona disponible con la misma carga.
3. Menor cantidad de aseos cumplidos.
4. Rotación de compañeros y, en el calendario, reducción de parejas repetidas
   entre quienes quedan disponibles. Estos criterios solo resuelven empates
   entre personas con la misma prioridad.
5. Fecha de referencia más antigua. Para cada aprendiz se toma la más reciente
   entre su último aseo cumplido y su último turno programado considerado.
   Si no hay fechas, tiene prioridad quien nunca tuvo turno.
6. Sorteo entre quienes siguen empatados.

Cada asignación aumenta inmediatamente la carga proyectada. Esto evita que
un calendario completo repita a los mismos aprendices porque sus turnos nuevos
todavía no se han cumplido. Evitar sesiones consecutivas nunca permite elegir
a alguien con mayor carga total. Si solo hay dos personas elegibles, pueden repetir.

## Responsabilidades y contratos

- `app/services/aseo_cola.py` contiene la selección y su explicación, sin consultas
  ni escrituras en la base de datos. Recibe candidatos elegibles, contadores,
  cargas, fechas, historial de parejas y un generador aleatorio opcional.
- `app/services/aseo.py` conserva la elegibilidad, la asistencia, las exclusiones,
  las consultas y la persistencia. Consume la misma selección para el calendario,
  las suplencias, los compañeros de reposición y los reemplazos por deshabilitación.
- `tests/test_aseo_equidad.py` verifica el desempate en ambos cupos, el reparto de
  un calendario, los límites de la selección y los mensajes de auditoría.
- La suite existente verifica permisos, festivos, exclusiones, cumplimiento
  individual y conservación de turnos cumplidos, manuales y pasados.

No se modifica el esquema ni se recalculan datos reales durante las pruebas.
La generación mantiene el alcance temporal existente: los pendientes anteriores
al rango y los protegidos dentro de este aportan carga; los futuros fuera del
rango no adelantan la carga del periodo actual.

Se extrajo la selección porque tenía dos implementaciones que podían divergir.
Mantener ambas habría conservado el riesgo; un nuevo patrón de infraestructura
o una migración de datos no son necesarios. Las pruebas usan SQLite en memoria
y forman parte de la suite que CI ejecuta con la compuerta de funciones al 100 %.
