# Personalización persistente del panel del aprendiz

Fecha: 7 de octubre de 2026.

El aprendiz debe recuperar su apariencia al recargar, volver a ingresar o cambiar de navegador. El panel conserva los datos académicos y las alertas existentes; la personalización solo modifica su presentación.

## Diagnóstico confirmado

La implementación anterior escribía únicamente en `localStorage`, bajo una clave por aprendiz. No había una tabla ni una ruta para guardar preferencias. La función que leía esas preferencias no se ejecutaba al iniciar. Además, el selector del botón de personalización no correspondía al identificador de la plantilla. El alias se intentaba aplicar a un elemento inexistente. Estos defectos explicaban que el guardado no sobreviviera al recorrido habitual del usuario.

Los enlaces de GitHub y Notion ya tienen rutas y campos persistentes propios. Se mantienen sus contratos y pruebas.

## Decisión de arquitectura

Se conserva Flask, Jinja, SQLAlchemy y Alembic. La funcionalidad se organiza como un módulo independiente en `app/features/personalizacion_aprendiz/`, con modelo, servicio y rutas. El registro de la aplicación importa el módulo; el servicio consume el modelo y la sesión SQLAlchemy. La interfaz consume exclusivamente las rutas públicas y no importa detalles de persistencia.

- `models.py`: una fila por aprendiz, con preferencias JSON, foto binaria y revisión positiva. La relación elimina la personalización al eliminar al aprendiz.
- `service.py`: validación de catálogos, tamaños, revisión, normalización de fotos y escritura transaccional.
- `routes.py`: identidad de sesión, permisos, respuestas y errores de lectura o escritura.
- `_personalizacion.html`: formulario del editor, integrado con los diálogos existentes.
- `aprendiz_personalizacion.js`: borrador, lectura, guardado confirmado y sincronización del panel.
- `aprendiz_personalizacion.css`: apariencia, fondos, distinciones y adaptación del editor.

Se usa una tabla separada para que los campos visuales no se mezclen con asistencia, juicios, puntajes o roles. La foto se guarda en la misma base de datos: una actualización del contenedor no depende de conservar una carpeta de archivos adicional. Las imágenes se reducen a 512 px y se guardan como JPEG sin metadatos.

Se descartan un nuevo proveedor de almacenamiento y una reescritura del dashboard: ambos amplían dependencias sin resolver mejor este problema. Los fondos disponibles son patrones del catálogo; no se acepta CSS ni código arbitrario del usuario.

## Contrato de datos y concurrencia

`GET /aprendiz/<ficha_id>/personalizacion` devuelve `ok`, `preferences`, `revision`, `photoUrl` y `configured`. Una lectura sin registro devuelve valores iniciales y revisión cero, sin escribir datos. Las preferencias contienen `avatar`, `accent`, `themeName`, `motto`, `alias`, `background`, `sectionOrder` y `viewMode`.

`POST` en la misma ruta recibe un formulario multipart con `preferences` JSON, `revision`, `csrf_token`, `photo` opcional y `remove_photo` opcional. Solo confirma éxito después del commit. Una revisión obsoleta devuelve HTTP 409; la interfaz ofrece recargar antes de volver a guardar. Los errores de base de datos devuelven HTTP 503 y conservan el borrador en el editor.

`GET /aprendiz/<ficha_id>/personalizacion/foto` consulta únicamente la foto del aprendiz en sesión. Las respuestas usan `private, no-store`; la foto agrega `nosniff`. La identidad nunca se toma de un documento o identificador enviado por el formulario. Un acceso a otra ficha, una sesión ausente o un aprendiz deshabilitado no puede modificar preferencias.

La foto acepta JPEG, PNG o WebP con contenido verificable, hasta 2 MiB y 16 megapíxeles. El servicio rechaza archivos vacíos, contenido corrupto, formatos no permitidos y campos ajenos al contrato. El alias admite hasta 30 caracteres y el lema hasta 80. El cliente presenta ambos como texto.

## Experiencia del aprendiz

El editor permite elegir avatar o foto, color, fondo, alias, lema, modo de vista y orden de las secciones disponibles. Los botones para subir o bajar secciones funcionan con teclado y en celular. La estructura de cada sección y sus pestañas se conserva al moverla.

El borrador no reemplaza la apariencia confirmada hasta que responde la base de datos. Cancelar descarta el borrador. Restablecer prepara los valores iniciales y la eliminación de la foto; el aprendiz debe guardar para confirmarlos. Si existen preferencias antiguas solo en ese navegador y aún no hay un registro persistido, el editor ofrece recuperarlas de forma explícita.

Las distinciones de oro, plata y bronce dependen de la posición calculada por el ranking. No se guardan como una opción editable y la ruta rechaza intentos de enviar puntajes, roles o insignias.

## Criterios de aceptación

1. Guardar alias, lema, color, fondo, orden, modo de vista y foto; recuperarlos desde una sesión nueva sin `localStorage` y después de reiniciar el servidor de pruebas.
2. Rechazar el guardado desde otra ficha o aprendiz deshabilitado, sin efectos en los datos existentes.
3. Conservar preferencias y foto anteriores ante errores de validación o de commit, y no mostrar confirmación de guardado fallido.
4. Detectar dos escrituras con la misma revisión y conservar únicamente la primera confirmada.
5. Cancelar un restablecimiento conserva los datos; confirmar un restablecimiento elimina la foto y persiste los valores iniciales.
6. Mostrar los controles completos a 320, 390, 768, 1440, 1920 y 2560 px, con prueba adicional al 200 % de zoom.
7. Mantener un único head Alembic, con upgrade/downgrade que conserven las tablas y los registros académicos anteriores.

## Verificación y puesta en uso

Las pruebas de Python usan una base SQLite aislada y cubren efectos reales de las rutas, transacciones y migración. Las pruebas JavaScript cubren estado e interacciones. Las pruebas de navegador ejecutan Flask y la base de pruebas, con CSRF habilitado, recarga y reinicio del servidor. La CI mantiene las compuertas de cobertura y añade la funcionalidad a las suites existentes.

La migración `q40personalizacionaprendiz`, descendiente de `p39portafolioaprendiz`, crea la tabla sin modificar registros de aprendices existentes. El despliegue debe ejecutar el upgrade habitual antes de servir la interfaz nueva. Este trabajo no modifica la base de producción ni publica una nueva versión por sí mismo.

Las pruebas automatizadas no acreditan el tratamiento autorizado de fotos reales. Los pendientes institucionales se registran en `docs/legal/`. La autenticación del aprendiz por documento corresponde al contrato heredado del proyecto; evaluar una autenticación más fuerte requiere un alcance separado.

## Evidencia del cierre local

- Python: 842 pruebas aprobadas; 677 de 677 funciones de producción alcanzadas; cobertura agregada de líneas y ramas de 84,48 %, por encima del umbral vigente de 75 %. El backend de personalización alcanza 100 % de líneas y ramas.
- JavaScript: 64 pruebas aprobadas; el módulo de personalización alcanza 100 % de funciones y líneas, con 95,03 % de ramas.
- Navegador: suite de 16 pruebas aprobada. Después de los últimos ajustes del personalizador, sus seis recorridos pasan nuevamente, incluido contraste del botón de guardar en tema oscuro, anchos obligatorios y viewport equivalente al zoom del 200 %.
- Persistencia: base SQLite aislada, sesiones nuevas y reinicio del servidor de pruebas. No se ha ejecutado esta migración en una base PostgreSQL de producción.
- Compuertas: `WorkingTree` y revisión estricta de reversibilidad superadas. Modularidad informa dos advertencias documentadas, sin errores. El índice de Codebase Memory fue actualizado.
- Dependencias: Pillow 12.3.0 no presenta avisos en la auditoría realizada. La auditoría completa detecta 19 avisos en cuatro dependencias heredadas: Flask, python-dotenv, pypdf y Werkzeug. Su actualización queda pendiente y no se certifica la seguridad completa de la aplicación.

Los reportes locales quedan en `test-results/`; las mismas suites se incorporan a CI. Una corrección de la prueba de aseo usa el siguiente día laboral disponible, para evitar que un fin de semana cambie el resultado esperado sin modificar la regla de producción.
