# Prioridad de los turnos de aseo

## Problema comprobado

El calendario comparaba primero la carga total (aseos cumplidos más pendientes),
pero, ante un empate, la antigüedad o la rotación de parejas podían adelantar a
quien tenía más aseos cumplidos. La selección de suplentes ya usaba otro orden.
Las pruebas de regresión reproducen esta diferencia con registros persistidos.

## Regla de selección

Los dos cupos del turno usan los mismos criterios, en este orden:

1. Menor carga total: aseos cumplidos más turnos ya programados de **todo el
   horizonte** (no solo del rango que se está calculando).
2. Descanso obligatorio: no se repite a quien fue asignado en la sesión anterior
   mientras exista otra persona elegible. Antes se relajaba el descanso y se podía
   repetir a la misma persona dos días seguidos aunque hubiera reemplazo.
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
todavía no se han cumplido. La regla nunca entrega el cupo a quien tiene más
carga total si existe una alternativa con menos: es el defecto que reportaba
"el sistema asigna primero a quienes más veces han hecho aseo". Si solo hay dos
personas elegibles, pueden repetir.

## Responsabilidades y contratos

- `app/services/aseo_cola.py` contiene la selección y su explicación, sin consultas
  ni escrituras en la base de datos. Recibe candidatos elegibles, contadores,
  cargas, fechas, historial de parejas y un generador aleatorio opcional.
- `app/services/aseo.py` conserva la elegibilidad, la asistencia, las exclusiones,
  las consultas y la persistencia. Consume la misma selección para el calendario,
  las suplencias, los compañeros de reposición y los reemplazos por deshabilitación.
- `app/services/aseo_calendario.py` valida la lista de días elegidos y centraliza
  la semana predeterminada y los nombres usados en los selectores.
- `app/services/aseo_limpieza.py` elimina los pendientes en días no permitidos,
  resuelve sus referencias de intercambio y devuelve el número eliminado.
  Usa la transacción de la generación; no confirma cambios por separado.
- `app/routes/aseo.py` entrega las opciones al formulario del instructor y del
  aprendiz y pasa la selección al mismo servicio de generación.
- `tests/test_aseo_equidad.py` verifica el desempate en ambos cupos, el reparto de
  un calendario, los límites de la selección y los mensajes de auditoría.
- `tests/test_aseo_equidad_total.py` fija la equidad sobre la carga total: los
  pendientes de otros rangos consumen cupo, el cálculo nunca elige a quien más
  tiene, la inasistencia se compensa con la menor carga y el botón "Calcular
  turnos" informa el delta resultante.
- La suite existente verifica permisos, festivos, exclusiones, cumplimiento
  individual y conservación de turnos cumplidos, manuales y pasados.

No se modifica el esquema ni se recalculan datos reales durante las pruebas.
La generación cuenta como carga los pendientes **anteriores y posteriores** al
rango; solo quedan fuera los pendientes que el propio rango va a redistribuir,
porque esos se asignan de nuevo dentro del cálculo. Así un mes calculado de forma
independiente no vuelve a premiar a quien ya tiene aseos programados en otro mes.

El selector semanal se incluye en los formularios del instructor y del aprendiz.
De lunes a viernes quedan marcados por defecto; las selecciones de sábado y
domingo autorizan esos días para el cálculo solicitado. El servidor aplica la
misma validación a la lista recibida y rechaza selecciones vacías o fuera del
calendario semanal. Las sesiones que caen en días no seleccionados no se crean.
Al generar, se eliminan sus turnos pendientes dentro del rango solicitado antes
de recalcular la distribución, aunque sean manuales o de fechas pasadas. Los
turnos cumplidos y los registros de asistencia se conservan. Los días elegidos
de forma explícita, incluidos sábado y domingo, siguen permitidos.

## Criterios de regresión de la limpieza

- Dado un rango con sábados y domingos programados o intercambiados, cuando se
  generan aseos con la selección predeterminada, entonces sus pendientes se
  eliminan y dejan de aportar carga e historial de parejas al nuevo cálculo.
- Dado un turno pendiente en otro día desmarcado, cuando se aplica esa selección,
  entonces también se elimina; la restricción semanal prevalece sobre conservar
  asignaciones manuales, pasadas o pendientes sin recalcular.
- Dado un aseo cumplido o un turno fuera del rango, cuando se limpia el calendario,
  entonces permanece intacto. Las sesiones y asistencias nunca se eliminan.
- Dado un intercambio de otro turno que referencia uno eliminado, cuando se
  limpia, entonces se retira la referencia recíproca y se rechaza si estaba pendiente.
- Dado un fin de semana seleccionado explícitamente, cuando se genera, entonces
  se conserva o recalcula; una selección vacía se rechaza antes de borrar datos.
- Dado el mismo rango y selección, cuando se repite la generación, entonces no
  se duplican turnos y el resultado informa cero eliminaciones adicionales.
- Dada una generación autorizada desde instructor o aprendiz, cuando solo se
  borran pendientes, entonces se confirma el número eliminado en el mensaje.
- Dado un turno cumplido en un día laborable, sábado, domingo o festivo, cuando
  se recalcula incluso sin conservar manuales ni proteger pasados, entonces
  todos sus campos permanecen iguales. Los cumplimientos parciales conservan
  ambas marcas y solo se cuenta a quien sí cumplió; las marcas históricas vacías
  mantienen su compatibilidad. Repetir el cálculo no duplica los contadores.
- Dado un calendario con cargas desiguales, reservas manuales y pendientes
  anteriores al rango, cuando se limpia y recalcula, entonces cada cupo automático
  se asigna a una persona elegible con la menor carga disponible. El historial
  cumplido y las reservas protegidas se conservan; los pendientes eliminados
  no aportan carga. `tests/test_aseo_preservacion.py` verifica estos contratos
  con cuatro sorteos reproducibles y compara todos los campos del historial.

El ingreso por fecha manual sigue operando de forma independiente.

Se extrajo la selección porque tenía dos implementaciones que podían divergir.
Mantener ambas habría conservado el riesgo; un nuevo patrón de infraestructura
o una migración de datos no son necesarios. Las pruebas usan SQLite en memoria
y forman parte de la suite que CI ejecuta con la compuerta de funciones al 100 %.

## Término general acumulativo y cortes pedagógicos

1. **Independencia frente a cortes pedagógicos:**
   Los cortes pedagógicos estructuran las calificaciones y las asistencias por etapas,
   pero no reinician ni alteran el contador acumulado de turnos de aseo. La equidad
   del aseo es un compromiso formativo transversal a toda la ficha; por ende, el
   contador `ContadorAseo.veces_aseo` se mantiene en término general sin reiniciarse
   al abrir, cerrar o cambiar de corte.

2. **Métricas de transparencia y gestión:**
   Para brindar claridad tanto del periodo en curso como del balance general, las
   interfaces del instructor y del aprendiz presentan tres columnas diferenciadas:
   - **En periodo (`veces_periodo`):** Muestra los turnos efectivamente cumplidos
     por el aprendiz dentro del mes o rango de fechas visualizado (calculado con
     `contar_cumplidos_en_periodo`).
   - **Cumplidos (`veces_total`):** Muestra la totalidad histórica de turnos
     cumplidos por el aprendiz en la formación (`ContadorAseo.veces_aseo`).
   - **Programados (`veces_pendientes`) y Total (`veces_comprometidas`):** muestran
     los turnos pendientes y la suma que realmente usa el algoritmo para decidir.
     La columna Total es la que debe mirar el instructor para comprobar la equidad.

3. **Criterio rector de asignación:**
   El cálculo de cola justa (`app/services/aseo_cola.py` y
   `app/services/aseo_motor_puro.py`) prioriza la carga total (cumplidos +
   programados de todo el horizonte) y la fecha de referencia más antigua (quien
   lleva más tiempo sin realizar aseo o nunca lo ha hecho), garantizando que todos
   los aprendices alcancen el mismo número de turnos a lo largo del proceso formativo.

## Inasistencia y equidad

Cuando alguien no asiste, el turno del día se resuelve en dos pasos:

1. Se busca un suplente entre los presentes con la **menor carga total**, nunca
   entre los que ya acumulan más turnos. El ausente no suma el turno a su contador.
2. Se le programa una reposición solo si su carga total quedó por debajo de la de
   sus compañeros. Si otra persona ya cubrió el turno y el ausente conserva sus
   pendientes, no se le agrega otro turno: así no se sobrecompensa ni se duplica
   la reposición. La reposición se empareja con quien menos carga total tiene.

Ninguna inasistencia desaloja turnos futuros ya publicados de otros aprendices.
Para reequilibrar todo el horizonte existe `rebalancear_turnos_pendientes`, que
solo cambia parejas de turnos pendientes existentes (no crea ni borra), respeta
manuales e intercambios aceptados y se ejecuta desde el botón "Calcular turnos"
con la opción **Equilibrar todo el calendario**.

