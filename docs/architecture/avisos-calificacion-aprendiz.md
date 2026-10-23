# Avisos de calificación para aprendices

## Flujo técnico

Las calificaciones individuales y grupales, las aprobaciones presenciales y los cambios efectivos de juicios evaluativos crean una notificación persistente en la misma transacción del cambio académico. La primera carga de juicios de una ficha no genera avisos; las cargas posteriores anuncian los cambios consolidados, una vez por aprendiz y reporte. En las páginas del aprendiz, el navegador consulta avisos nuevos cada 15 segundos y deduplica por identificador. El audio solo se activa con una acción explícita en esa página. «Lectura tranquila» conserva el texto y silencia el tono.

Las suscripciones Web Push son voluntarias y quedan asociadas al aprendiz de la sesión. El worker existente procesa el buzón después de confirmar el cambio académico, reintenta fallos temporales y elimina endpoints vencidos. El contenido que viaja al proveedor solo indica que hay una actualización; el clic abre el centro de notificaciones del panel. La calificación y el documento no viajan en el texto ni en la URL.

## Configuración y activación

`WEB_PUSH_ENABLED` vale `false` por defecto. La clave pública, la clave privada y el asunto VAPID se reciben desde secretos del entorno como `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY` y `VAPID_SUBJECT`. La clave privada no se almacena en el repositorio. El panel solo ofrece la suscripción cuando Push está habilitado y las tres variables están configuradas.

El endpoint y las claves de cada suscripción se cifran en la base de datos con una clave derivada de `SECRET_KEY`; el índice de búsqueda conserva solo la huella SHA-256 del endpoint. Push también se deshabilita si la aplicación arrancó con una `SECRET_KEY` efímera. Cambiar `SECRET_KEY` requiere que los aprendices vuelvan a registrar sus dispositivos.

## Pendiente antes de aprendices reales

La institución debe confirmar el responsable del tratamiento, la población y la posible participación de menores, la base aplicable, el aviso de privacidad, los proveedores activados por cada navegador y las transferencias internacionales asociadas. También debe definir el plazo de conservación y eliminación de endpoints y claves de suscripción. Hasta entonces, mantenga `WEB_PUSH_ENABLED=false`. La revisión técnica no equivale a autorización legal ni institucional.
