# Mensaje listo para el grupo — Trazora FSM

Equipo, ya está disponible el traspaso técnico de **Trazora FSM**. Para evitar que frontend y backend trabajen con rutas distintas, usar los documentos de `docs/trazora/` como referencia inmediata y tomar los diagramas antiguos como arquitectura **objetivo**, no como lista de endpoints ya disponibles.

**Qué tenemos:** MS0 login/sesiones, MS1 Clientes, MS2 Técnicos/jornadas, MS3 Órdenes, MS4 Agenda/visitas y MS5 Partes/S3 en primera versión; se desplegaron y se probaron con CLIMALIMA/FRIOSUR. El backend está en https://github.com/leonardopanduro-rgb/trazora-fsm. El repositorio de colaboración del equipo es https://github.com/rvcuba-utec/cloud-project-v2.

**Frontend:** avanzar ya con React y Amplify. Primero login y layout mostrando el tenant/rol; después clientes y técnicos, órdenes, agenda y borradores/evidencias. Todas las llamadas protegidas usan `Authorization: Bearer <token>` y la empresa se determina en el backend. El token no se publica ni se guarda en el repositorio; los archivos se suben directamente a S3 con POST prefirmado, **sin Bearer**. Seguir `02_CONTRATOS_API.md` y `03_GUIA_FRONTEND.md` para las rutas y el orden de implementación.

**No están listos todavía:** MS6 Analítica del diagrama, gestión completa de usuarios, cierres/cancelaciones, iniciar/finalizar visitas, publicar/consumir eventos SNS/SQS y carga de 30k registros por servicio. No llamar rutas que no existen ni simular cierres como si fueran exitosos. El backend está terminando esos puntos en paralelo (`04_BACKEND_PENDIENTES.md`).

**Reparto sugerido para el equipo:**
- Persona A: shell React, login, contexto de sesión, errores 401.
- Persona B: Clientes y Técnicos (formularios, listados y jornadas).
- Persona C: Órdenes y Agenda, validaciones/horarios y conflictos 409.
- Persona D: Partes, actualización con versión y evidencia S3.
- Persona E / integración: Amplify, pruebas de dos tenants, diseño responsive y evidencias. Si somos menos personas de frontend, se combinan tareas.

Crear ramas por funcionalidad, abrir PRs pequeños y no subir contraseñas, tokens o credenciales AWS. Para dar una tarea por terminada: compila, utiliza API real, muestra error/estado correcto, respeta el tenant y deja evidencia.

**Fechas:** primer avance para exposición hasta **14/11**; entrega final **22/11 a las 23:59**. Prioricemos que la web demuestre un flujo real de dos tenants antes de mejorar detalles visuales. Si una ruta falta, anotarla como dependencia backend en el PR, sin bloquear el resto de pantallas.
