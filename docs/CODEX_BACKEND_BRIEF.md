# Encargo listo para Codex — backend Trazora FSM sin frontend

Trabaja únicamente en este repositorio: https://github.com/leonardopanduro-rgb/trazora-fsm

**Rama base obligatoria:** `integracion/backend-datos-renzo-2026-11-04` (NO usar ni alterar `main`; crear una rama de feature desde ella para tus cambios). **Alcance: solo backend, scripts de datos, infraestructura Serverless, tests y documentación. No modificar `frontend/` ni `handoff/cloud-project-v2/frontend/`.** No hacer despliegues ni modificar cuentas AWS sin aprobación explícita.

## Contexto correcto

- Hay seis microservicios reales MS0–MS5 y un stack declarativo para SNS/SQS; ya hubo pruebas de API exitosas en el laboratorio, pero el flujo FSM de finalización/eventos **aún no está implementado**.
- Importamos en `scripts/seed/` los scripts de `rvcuba-utec/cloud-project-v2` rama `avance-1` (mismo árbol que `datos`, merge PR #1); el plan de `renzo` está archivado en `docs/referencias/PLAN_RENZO_ORIGINAL_2026-11-03.md`. **No intentes un git merge normal con estas ramas de otro repositorio: tienen historiales distintos; ya hicimos importación por archivos**.
- Estudia `docs/INTEGRACION_BACKEND_2026-11-04.md`, `docs/FASE_EVENTOS_INFRA.md`, `docs/MS0_LOGIN.md`, `docs/MS2_TECNICOS.md`, `docs/MS3_ORDENES.md`, `docs/MS4_AGENDA.md`, `docs/MS5_PARTES.md` y los scripts existentes ANTES de cambiar contratos.
- La documentación fuente de Renzo describe MS6 Analítica como objetivo, **no está desplegado**. No lo construyas hasta tener integrados los seis actuales y verificadas las prioridades.

## Trabajo solicitado (en PRs o commits pequeños y comprobables)

### 1. Diagnóstico reproducible (primero)
- Comparar el código actual MS0–MS5 con los contratos del equipo; generar matriz de endpoints existentes/pendientes y decisiones incompatibles.
- Ejecutar tests locales y `python -m py_compile`. Anotar resultados reales, no fingir despliegues AWS.
- Validar `scripts/seed/*`: generar un lote pequeño, validar JSONL/manifest, simular carga SQLite e interrupción/reanudación. Reportar hallazgos y corregir defectos sin alterar datos de demo.

### 2. MS2 estado de técnico
- Implementar `PATCH /tecnicos/{tecnico_id}/estado` con body `{"activo":true|false}`.
- Solo ADMIN del tenant autenticado; 404 para ID ajeno, 400 para input inválido, 409 para desactivar con visitas futuras activas o aplicar una política segura documentada.
- No permitir que técnicos inactivos reciban nuevas jornadas o visitas; reactivación debe funcionar. Agregar tests unitarios y de integración.

### 3. Ciclo de atención y EDA
- MS4: iniciar/reprogramar/cancelar visita con controles de estado, transacciones para bloques/contadores y resistencia a doble clic/duplicados.
- MS5: finalizar parte solo para visita válida, con evidencia confirmada, control de versión, usuario/rol/tenant correctos. Guardar estado final + OUTBOX atómicamente.
- Infra `infra/eventos/serverless.yml`: validar SNS topic, dos colas SQS y DLQs. Respetar filtros `FilterPolicyScope: MessageBody` que esperan campo `event_type` dentro de JSON. No convertir los consumidores en endpoints públicos.
- Publicador DynamoDB Streams → SNS con recuperación y controles de duplicación; dos consumidores SQS (Agenda y Órdenes) con INBOX/idempotencia y escritura transaccional. Eventos de `ParteFinalizado` deben actualizar MS4 y MS3 de forma verificable y segura entre tenants; caso de fallo/reintentos a DLQ.
- MS3: estados e historial coherentes, cierre/cancelación bloqueando visitas pendientes cuando corresponda.
- Pruebas: dos tenants, rol sin permiso, token revocado, visita duplicada, mensaje duplicado, concurrencia, 409/404/401, sin fuga de información.

### 4. Carga masiva de datos (sin escribir AWS hasta aprobación)
- Revisar generador importado: 37 000 registros principales por servicio, 3 tenants, vínculos cliente→orden→visita→parte y registros auxiliares consistentes.
- Python 3.13.2 esperado por los scripts; la EC2 previa usaba Python 3.10. Evitar sobrescribir Python del sistema.
- `cargar_datos.py` escribe por `put_item` condicional, 5/s por defecto, límite 50/s; con ~222k registros principales y auxiliares superaríamos la duración de las credenciales temporales de 4 h si se usa velocidad por defecto. Diseñar carga eficiente, reanudable, segura y con control de colisiones; justificar si se usa `batch_writer` frente a escrituras condicionales.
- Ejecutar únicamente tests locales y simulación/piloto en SQLite; proponer procedimiento de inspección/piloto AWS con parámetros y confirmaciones humanas. NO ejecutar `--apply` sin aprobación explícita.
- Crear reporte de conteos por servicio y tenant; separar entidades de negocio de elementos auxiliares.

### 5. Monitoreo y documentación
- Logs JSON INFO/ERROR sin secretos y métricas CloudWatch; evidencias reproducibles de las pruebas.
- Corregir documentación y diagramas para reflejar el estado implementado, no la propuesta futura. Actualizar README con comandos y matriz de fases pendientes.
- Entregar al finalizar: archivos modificados, tests ejecutados y salidas, decisiones tomadas, bloqueos AWS Academy, riesgos y pasos manuales para despliegue; abrir PR contra `integracion/backend-datos-renzo-2026-11-04` (o dejar cambios en rama feature para revisión).

## Reglas no negociables
- No frontend, no despliegue real sin autorización, no borrar o recrear tablas de demostración, no `serverless remove` y no exponer credenciales/tokens/URLs S3 firmadas.
- No reescribir automáticamente todos los servicios ni hacer un PR gigantesco; dividir por temas y conservar compatibilidad con los contratos en uso.
- Consultar cuando una decisión irreversible afecte datos, permisos de laboratorio o contratos expuestos.
- Documentar con precisión qué código está probado localmente y qué todavía NO fue verificado en AWS.

Primera acción: resume hallazgos del inventario, corre pruebas locales y abre un primer PR pequeño para **MS2 estado de técnico**. Después continúa por etapas con la finalización del flujo y la mensajería.
