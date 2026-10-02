# Estrategia de Gamificación Emocional y Rendimiento Formativo SENA
**Centro de Gestión Agroempresarial y del Oriente — Subsede Vélez**  
*Programa de Tecnólogo en Análisis y Desarrollo de Software (ADSO)*

---

## 1. Justificación Pedagógica y Diagnóstico Emocional

En los entornos de formación técnica y tecnológica, la evaluación cuantitativa tradicional suele generar dos problemas psicológicos graves si no se contextualiza adecuadamente:
1. **La mancha de incertidumbre y saturación visual**: En mediciones con alta frecuencia (como 61 cortes o registros continuos), graficar números y fechas sobre cada punto produce saturación cognitiva y colisión gráfica, impidiendo al aprendiz entender su verdadera trayectoria.
2. **La trampa del castigo por apertura de corte**: Cuando un nuevo corte evaluativo abre en cero evidencias calificadas, el puntaje temporal puede caer drásticamente (por ejemplo, de 85.0 a 0.0). Calificar esta variación como *"CRÍTICO"* genera indefensión aprendida (*learned helplessness*), frustración y desconexión con el proceso formativo.
3. **Injusticia percibida en el trabajo colaborativo**: Si una tarea grupal solo registra evidencias a nombre del aprendiz que subió el archivo, los demás integrantes del equipo sufren penalizaciones invisibles que destruyen la confianza interna del escuadrón.

Esta estrategia transforma el seguimiento académico en un **sistema de acompañamiento formativo, mérito colectivo y superación continua**, apoyándose en la psicología de la motivación intrínseca.

---

## 2. Marco de Gamificación Formativa: Modelo Octalysis Adaptado al SENA

Implementamos una arquitectura motivacional sustentada en 5 núcleos de la teoría *Octalysis* de Yu-kai Chou:

### 2.1 Núcleo 1: Propósito Épico y Trascendencia (Epic Meaning)
- **Concepto**: El aprendiz no entrega tareas para "sacar una nota", sino para convertirse en un tecnólogo íntegro capaz de liderar soluciones de software en su región.
- **Aplicación**: Cada módulo formativo y cada reto en equipo se presenta como un hito de madurez profesional. Las medallas no son adornos; condecoran competencias técnicas, puntualidad y liderazgo comunitario.

### 2.2 Núcleo 2: Desarrollo y Realización Personal (Development & Accomplishment)
- **Curva SVG Inteligente**: 
  - Las fechas en el eje X se distribuyen limpiamente (4 a 6 marcas equidistantes) para que la línea temporal siempre sea legible.
  - Las etiquetas de puntaje se reservan para el hito máximo (*pico histórico*) y el último corte activo, eliminando el ruido visual.
  - Línea de meta visible al 70%, permitiendo saber con exactitud cuánto falta para aprobar.
- **HUD Interactivo de Inspección**: Al tocar o pasar el cursor por cualquier punto del gráfico, una tarjeta flotante muestra fecha, puntaje, porcentaje de asistencia y evidencias sin distorsionar la gráfica.

### 2.3 Núcleo 3: Empoderamiento de la Creatividad y Retroalimentación Inmediata
- **Diagnóstico Empático Contextual**: Si un aprendiz experimenta una caída tras abrir un corte, el sistema le recuerda:  
  *«Tu puntaje tuvo una variación de -X pts en la medición más reciente. Esto suele asociarse a la apertura de un nuevo corte evaluativo o evidencias pendientes por calificar. Tu récord histórico de Y pts demuestra tu capacidad técnica para recuperarte rápidamente.»*
- **Ruta de Rescate Formativo en 3 Pasos**:
  1. *Cargar evidencias pendientes*: Acción prioritaria para recuperar puntos inmediatos.
  2. *Asistencia al 100%*: Garantía del puntaje base mediante constancia en el aula.
  3. *Desafíos de escuadrón*: Sumar mérito formativo mediante retos de equipo.

### 2.4 Núcleo 5: Influencia Social, Afinidad y Escuadrones Formativos (Social Influence)
- **Liga de Escuadrones**: La competencia individual aísla; la competencia de grupos une y protege al aprendiz en riesgo.
- **Puntuación Transparente de Equipos**:
  - `+15.0 puntos` por cada medalla o condecoración colectiva asignada por el instructor.
  - `+10.0 puntos` por cada reto o tarea grupal entregada dentro del plazo.
  - `+5.0 puntos` por entrega extemporánea con justificación formativa (estimulando no rendirse).
- **Acreditación Automática para Todos los Miembros**: Al enviar la evidencia grupal, el mérito y cumplimiento se acreditan a cada integrante activo del equipo, eliminando penalizaciones por delegación de subida.
- **Podio Formativo**: Reconocimiento visible con insignias de podio (🥇 Oro, 🥈 Plata, 🥉 Bronce).

### 2.5 Núcleo 7: Maestría, Reconocimiento y Resiliencia (Unpredictability & Curiosity)
Se crearon cuatro nuevas condecoraciones de mérito que el instructor puede otorgar o activar automáticamente:
1. **🏆 Reto Grupal Oro (`RETO_GRUPAL_ORO`)**: Conquistaron la máxima calificación en un desafío colectivo complejo.
2. **🤝 Sinergia de Equipo (`SINERGIA_EQUIPO`)**: Entrega ejemplar con aportes verificados de todos sus integrantes.
3. **💡 Innovación Colectiva (`INNOVACION_COLECTIVA`)**: Solución grupal que superó los requisitos técnicos estándar con creatividad y buenas prácticas.
4. **🛡️ Resurgimiento Heroico (`RESURGIMIENTO_HEROICO`)**: Escuadrón o aprendiz que superó un corte difícil y recuperó la senda aprobatoria con constancia.

---

## 3. Dinámica Operativa para el Instructor SENA

Para asegurar que la gamificación cumpla su propósito pedagógico en el CGAO:
1. **Lanzar 'Desafíos Semanales' en Clase**: Asignar retos grupales con plazo acotado y anunciar la medalla especial que obtendrá el escuadrón ganador.
2. **Monitorear el Podio en la Sesión**: Iniciar la clase proyectando brevemente el podio de la liga para felicitar avances y estimular a los equipos rezagados.
3. **Activar Rescate Oportuno**: Cuando el sistema detecte un grupo con dificultades, el instructor puede asignar mentoría entre pares, premiando al aprendiz mentor con la insignia de *Sinergia de Equipo*.

---

## 4. Conclusión

Esta arquitectura equilibra la exigencia técnica del SENA con el bienestar emocional del aprendiz, transformando una métrica fría en una experiencia de aprendizaje colaborativa, motivante y humana.
