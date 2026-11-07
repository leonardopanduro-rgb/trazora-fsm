# Backend Trazora — integración de datos y plan de Renzo (04/11/2026)

**Rama de trabajo:** `integracion/backend-datos-renzo-2026-11-04`, creada desde `main` de `leonardopanduro-rgb/trazora-fsm`. **No se ha fusionado con main ni desplegado nada en AWS por esta operación.**

## Qué se integró y de dónde

| Archivo incorporado | Fuente exacta | Propósito |
|---|---|---|
| `scripts/seed/generar_datos.py` | `rvcuba-utec/cloud-project-v2`, `avance-1`, commit `e265cd3a26c61111ad6cb592822ba18255e9c822` | Generador reproducible de datos sintéticos |
| `scripts/seed/validar_datos.py` | Misma fuente | Validación de claves, conteos, relaciones, horarios |
| `scripts/seed/cargar_datos.py` | Misma fuente | Simulación SQLite, inspección remota y carga condicional DynamoDB |
| `scripts/seed/README.md` | Misma fuente | Instrucciones de generación/validación/piloto |
| `docs/referencias/PLAN_RENZO_ORIGINAL_2026-11-03.md` | Rama `renzo`, commit `c16204b0d8b5a06e602ffd62f88a74fcacd0ffa2` | Referencia de implementación y riesgos, **no descripción del estado real actual** |

La rama `datos` ya fue integrada en `avance-1` mediante PR #1 del repositorio del equipo y posee el **mismo árbol de archivos** que `avance-1`; importarla dos veces es innecesario. No se hizo una fusión Git entre repositorios sin ancestro común: se copiaron archivos seleccionados, sin borrar nuestros MS0–MS5, tests y configuración de eventos.

## Estado verificable

- **MS0–MS5:** código en nuestro repositorio. El equipo reportó pruebas positivas en AWS Academy (autenticación, aislamiento, órdenes, agenda y borradores + S3). Esto no implica que el flujo de finalización FSM ya esté completo.
- **SNS/SQS:** `infra/eventos/serverless.yml` define topic, dos colas principales y dos DLQ. **No se ha confirmado desde la conversación el despliegue real del stack**, ni existen consumidores/publicadores.
- **Datos masivos:** ahora hay generador, validador y cargador importados. **No se ha demostrado generación/verificación íntegra ni carga real en la cuenta AWS**.
- **MS6 Analítica:** aparece en el plan de Renzo, **no está implementado**. El enunciado exige al menos 5 servicios; priorizar completar los seis existentes.
- **Frontend:** expresamente fuera del alcance de esta rama.

## Diferencias respecto al plan histórico de Renzo

El plan fuente, fechado 03/11, describe que en ese momento faltaba todo el código y propone endpoints que hoy todavía no están disponibles (`/visitas/{id}/iniciar`, `/partes/{id}/finalizar`, `/ordenes/{id}/cerrar`), junto con un MS6 opcional. Usarlo como referencia, **no como una lista literal de funcionalidades desplegadas**. El plan propone filtros SNS por **atributos**, pero `infra/eventos` actual usa `FilterPolicyScope: MessageBody`. Estandarizar el contrato y mantener sincronizados productor, suscripciones y documentación.

## Prioridad de trabajo exclusivamente backend

### P0 — cierre del flujo FSM, seguridad e integración

1. **MS2: activar/desactivar técnico.** Añadir `PATCH /tecnicos/{tecnico_id}/estado` con `{"activo":true|false}`, autorización ADMIN, tenant validado y control de visitas futuras. Test de inactivo en MS2/MS4 y reactivación.
2. **MS4: ciclo de visita.** Implementar `iniciar`, `reprogramar`, `cancelar` y finalización. No permitir reprogramaciones que solapen bloques; mantener contadores y liberaciones atómicas/idempotentes. Validar orden, especialidad, jornada, técnico y tenant.
3. **MS5: finalizar parte.** Validar visita en atención, asignación al técnico cuando corresponda, evidencias confirmadas y transición válida. Transacción parte FINALIZADO + registro OUTBOX con `event_id` único; no cerrar orden desde MS5 directamente.
4. **Eventos reales SNS/SQS.** Desplegar/verificar `trazora-eventos-dev`, activar Streams/outbox con publicador a SNS y consumidor independiente e idempotente en MS4 y MS3. Implementar INBOX/identificador de evento, reintentos, DLQ, recuperación y pruebas de mensaje duplicado. El evento `ParteFinalizado` deberá producir cambios verificables en MS4 y MS3.
5. **MS3: estados y cierre/cancelación.** Consumir eventos, registrar historial y controlar visitas activas antes de cerrar; proteger contra condiciones de carrera.
6. **MS0/MS1/MS2: funcionalidades incompletas.** CRUD de usuarios por tenant y roles, ubicaciones de clientes, ausencias/edición de técnicos según alcance. No implementar frontend aquí.

### P1 — datos, observabilidad y evidencias

7. **Datos sintéticos.** La rama importada apunta a **37 000 entidades principales por cada uno de seis servicios (222 000)**, aproximadamente 12 334 / 12 333 / 12 333 por tenant. Los archivos auxiliares se cuentan aparte. Confirmar requisitos del docente para MS0.
8. **Validar en local ANTES de AWS:** el README importado solicita Python **3.13.2**, `Faker==40.1.2` y `tzdata==2026.6`. La EC2 anterior tenía Python **3.10.12**; usar una venv de versión adecuada, **no reemplazar el Python del sistema ni romper Serverless**.
9. **Riesgo en la carga real:** `cargar_datos.py` escribe con `put_item` condicional (no usa `batch_writer`), máximo **50 escrituras/segundo** y por defecto **5/s**; 222k registros principales son, a ese ritmo, más de 12 horas sin contar auxiliares/consultas. Las credenciales de AWS Academy se renuevan cada ~4 h. Codex debe diseñar una carga reanudable, eficiente y documentada, pero sin eliminar las verificaciones de colisiones o el aislamiento de datos. Primero piloto pequeño **en entorno aislado y autorizado**; jamás ejecutar `--apply` sin revisión/confirmación humana.
10. **CloudWatch:** logs JSON estructurados INFO/ERROR con correlation_id, event_id y tenant_id cuando corresponda, sin claves/tokens/contraseñas; consultas Logs Insights y evidencias de éxitos, 4XX, 5XX, DLQ, duración de Lambdas.
11. **Entrega:** JSON de cada tabla, diagrama **implementado** vs propuesto, conteos por tenant, resultados de pruebas y evidencias, README actualizado. La entrega final del curso es 22/11/2026 a las 23:59 Lima; avance al 14/11.

## Orden de ejecución recomendado

1. `git switch integracion/backend-datos-renzo-2026-11-04` y revisar `git status`; no modificar `main`.
2. Verificar compilación y ejecutar los scripts de semillas en modo local en un entorno Python compatible. No cargar datos a AWS.
3. Implementar MS2 estado y pruebas de protección tenant/rol.
4. Completar ciclo de visita y parte, después publicadores/consumidores SNS/SQS (en etapas, con rollback documentado).
5. Probar flujo real `orden → visita → atención → parte → SNS → SQS → visita completada → orden actualizada` con CLIMALIMA y FRIOSUR, incluida una duplicación simulada del evento.
6. Validar y ensayar cargas de datos, inspeccionar tablas/credenciales/costos; solo después de aprobación hacer piloto y carga en AWS.
7. Abrir PR contra `main` de nuestro repositorio. Exigir revisión antes de fusionar.

**No hay un despliegue a AWS incluido en esta rama.** No guardar el token de GitHub ni credenciales del laboratorio en código, docs, logs o commits.
