# Backend, datos, eventos y entrega: trabajo pendiente

Esta guía prioriza lo que falta para cumplir la entrega del proyecto final. El equipo debe sincronizar esta lista con el estado real de AWS antes de cerrar tareas.

## P0: cerrar el recorrido de atención (MS0–MS5)

### MS0 — gestión de usuarios por tenant
- Implementar endpoints protegidos para alta, listar y administrar usuarios del propio tenant (solo ADMIN), y vínculo seguro entre usuario TECNICO y perfil MS2.
- No permitir que el cliente envíe arbitrariamente `tenant_id` o `rol=ADMIN`. Crear usuarios iniciales con procedimiento autorizado.
- Mantener hashing de contraseña, expiración de token, revocación e identidad validada.
- Añadir manejo de intentos fallidos de login y pruebas de roles. La demo actual solo usa ADMIN.

### MS1 Clientes
- Agregar ubicaciones del cliente (crear/listar/consultar por tenant) para que MS3 valide cliente y dirección al crear orden.
- Permitir edición/desactivación conservando historial de órdenes; paginar.

### MS2 Técnicos
- Gestionar ausencias y edición de jornadas sin invalidar reservas existentes.
- Validar que perfil técnico pertenece a la misma empresa que su usuario MS0, no por el valor que envíe la UI.

### MS3 Órdenes
- Estados esperados del diseño: ABIERTA, PROGRAMADA, EN_ATENCION, REQUIERE_REVISITA, PENDIENTE_DE_CIERRE, CIERRE_EN_PROCESO, CERRADA y CANCELADA.
- Implementar cambios por eventos; no cerrar automáticamente al llegar ParteFinalizado si falta confirmación de Agenda.
- Para cerrar, pedir a MS4 bloquear nuevas visitas y verificar `visitas_activas = 0`; reintentos idempotentes.

### MS4 Agenda
- Implementar iniciar visita, reprogramar, cancelar y finalizar tras parte, comprobando permisos/asignación.
- Cada reprogramación debe crear nuevos bloques y liberar antiguos **en una sola transacción**. Si falla, conservar la reserva previa.
- Disminuir el contador de visitas activas exactamente una vez al cancelar/finalizar; no liberar dos veces ante duplicados.

### MS5 Partes
- Añadir `POST /partes/{id}/finalizar`. Solo permitirlo para visita EN_ATENCION y técnico asignado; impedir un segundo parte final por visita.
- Comprobar evidencias CONFIRMADAS antes de finalizar.
- Guardar cambio de estado de parte + evento OUTBOX en una transacción. La respuesta puede indicar "guardado; sincronizando" hasta terminar consumidores.
- No crear "FINALIZADA" solo en la UI, ni cerrar orden al completar formulario.

## P0: eventos SNS/SQS funcionales

**La configuración del stack `infra/eventos` está preparada en GitHub. No se confirmó aquí su despliegue real.** Revisar CloudFormation antes de continuarlo.

Flujo a implementar:

```text
MS5 finaliza parte + OUTBOX atómicos en DynamoDB
     └── DynamoDB Streams → Lambda publicadora → SNS
           ├── SQS Agenda → consumidor idempotente → visita FINALIZADA
           │      └── OUTBOX VisitaCompletada → publicadora SNS
           └── SQS Órdenes → consumidor idempotente → historial / estado orden
```

- SNS/SQS deben estar separados por consumidor; usar filtros `event_type` que coincidan con el contrato elegido. **La infraestructura actual filtra por `event_type` en el JSON del cuerpo**, mientras que el diagrama antiguo del equipo habla de atributo SNS. Unificar: enviar `event_type` **dentro del cuerpo JSON** o cambiar infraestructura y documentación juntos.
- Cada mensaje lleva `event_id` único, `schema_version`, `tenant_id`, `aggregate_id`, `occurred_at`, `correlation_id` y `data`. Validar todos en consumidores.
- Implementar patrón OUTBOX + reintento/recovery para publicación recuperable. No publicar un evento falso si la transacción de negocio no terminó.
- Consumidores guardan marca INBOX y actualización de negocio en la misma transacción; soportar mensajes repetidos, atrasados y errores parciales.
- SQS visibility timeout, DLQ, logs CloudWatch y prueba de reenvío; registrar resultados de un evento en Agenda y Órdenes.

## P1: tres tenants y carga masiva por Python/boto3

Exigencia académica: **30 000 registros ficticios por microservicio divididos en tres tenants** (aproximadamente 10 000 para CLIMALIMA, FRIOSUR y TECNINORTE). Para los cinco servicios FSM: mínimo 150 000. Si MS0 también cuenta, seis servicios: al menos 180 000; **confirmar con profesor**. La propuesta del equipo menciona un MS6 Analítica, no implementado: si se añade deberá incluir también persistencia, prueba y carga según alcance acordado.

- Crear `scripts/seed/cargar_datos.py` en backend. Ejecutarlo **desde EC2** con credenciales temporales AWS Academy y boto3 directo a DynamoDB; **NO por API Gateway**.
- Orden de carga: usuarios activos mínimos de demo / perfiles inactivos si aplica, clientes, técnicos+jornadas, órdenes que refieren a clientes, visitas que refieren a órdenes/técnicos, partes que refieren a visitas.
- Semilla reproducible, datos totalmente ficticios, IDs consistentes por tenant, timestamps y estados compatibles.
- Usar `batch_writer` con reintentos y verificación de tablas/etapa antes de escribir. No alterar las cuentas activas de demo ni provocar notificaciones reales.
- Guardar informe por servicio/tenant/tipo de entidad; **no usar OUTBOX, INBOX, bloques técnicos ni marcadores como registros de negocio** para inflar las cifras.
- Verificar conteos con paginación de consultas/scan y reporte CSV/JSON; cuidar límites y créditos del laboratorio.

## P1: infraestructura, frontend y verificación

- Publicar React en AWS Amplify, asegurar CORS correcto de API Gateway y S3, y enlazar APIs con variables Vite. No exponer llaves AWS.
- Integrar flujo completo con dos empresas y cuenta técnica real cuando exista.
- Mantener configuración declarativa Serverless para todos los recursos de infraestructura, incluida mensajería y frontend según requisitos del curso. Registrar pasos manuales imprescindibles.
- Añadir pruebas de autenticación/roles, aislamiento, token expirado, conflictos de horario, doble clic, carga de evidencias, idempotencia de eventos, error de red y datos cruzados.
- Cuidar estado final de EC2, colas SQS y tablas DynamoDB; las políticas `DeletionPolicy: Retain` evitan borrado automático en varios recursos.

## Documentación y hitos

| Fecha / entrega | Evidencia que debemos tener |
|---|---|
| 14 nov. 2026 — exposición virtual / avance 30% | URL Amplify, login real dos tenants, capturas de llamadas/protección, diagrama **implementado** y plan del flujo/eventos |
| 22 nov. 2026 23:59 Lima — Canvas | Informe PDF/Word, PPT, repos públicos, pruebas, datos 3 tenants, arquitectura, script de carga y URLs |
| Semana 16 — presencial | Demo completa y recorrido reproducible; roles del equipo y fallbacks preparados |

El README y los diagramas del repositorio del equipo actualmente muestran **MS6 Analítica (séptimo servicio)** como si formara parte del runtime. Mantener la propuesta, pero marcar MS6 como "idea pendiente/optativa" o implementarlo y demostrarlo. **No inventar evidencia de despliegue**.
