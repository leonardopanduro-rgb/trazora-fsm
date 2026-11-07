# Trazora FSM — corte de integración y traspaso (7 de noviembre de 2026)

## Evidencia real de AWS Academy

**Cuenta de laboratorio:** la utilizada durante el taller (us-east-1, dev). No versionar credenciales temporales ni tokens.

La persona que opera AWS mostró capturas de DynamoDB y Lambda que confirman el siguiente recorrido de prueba con registros ficticios de `CLIMALIMA`:

- **MS5 Partes:** parte `4ce4ae3d-d83f-4a51-8b51-2176bcc121a0`, estado `FINALIZADO`; su OUTBOX `ParteFinalizado` (event ID `14012ddb-bd4b-4dd8-8750-cdc6de648dd1`) estaba inicialmente `PENDIENTE`.
- **SNS:** una prueba independiente con Lambda y `LabRole` obtuvo respuesta `statusCode:200` y `messageId` de SNS.
- **SQS:** existen cola de Agenda, cola de Órdenes y sus dos DLQ. Se comprobaron inicialmente vacías. Se ajustó la suscripción de Órdenes a los eventos implementados `ParteFinalizado` y `VisitaCompletada`.
- **Consumidores manuales:** `trazora-agenda-consumidor-dev-manual` y `trazora-ordenes-consumidor-dev-manual` fueron actualizados desde código de este repositorio y sus triggers SQS se habilitaron desde consola.
- **Resultado observado:** visita `ca0bc582-c982-4b93-95bd-27352fad550c` cambió de `EN_ATENCION` a **`FINALIZADA`** (atributo `finalizada_en=2026-11-07T03:18:59Z`); orden `a9b6acaa-8b60-4a5b-b99d-4535c0af4eaf` pasó a **`PENDIENTE_DE_CIERRE`**, `requiere_revisita=false`.

**Conclusión limitada:** hay una **prueba end-to-end exitosa** de propagación de eventos para un caso real de desarrollo. Eso NO demuestra todavía todos los casos, el aislamiento entre dos tenants en mensajería, reintentos, recuperación a DLQ, cierre formal de órdenes ni automatización completa del despliegue.

## Corrección de JSON/DynamoDB aplicada a main

CloudWatch de MS5 mostró `{\"operacion\":\"sns_publish\",\"error\":\"TypeError\"}`, debido a `Decimal` al serializar `aggregate_version`. Se corrigió la publicación de MS5 con `json_utils.decimal_default`; Agenda y el script de recuperación convierten también `Decimal`. Se agregaron pruebas de regresión; GitHub Actions reportó éxito para el último cambio de pruebas. Los cambios desplegados manualmente desde consola no se deben confundir con un despliegue Serverless reproducible hasta sincronizarlo.

## Estado de arquitectura

- MS0–MS5: funciones y stacks observados; contratos actuales en `backend/*/serverless.yml`.
- SNS/SQS: recursos reales existentes **fuera** de `trazora-eventos-dev`, por lo que **NO** ejecutar `serverless deploy` en `infra/eventos` sin importar/conciliar recursos.
- Dos Lambdas manuales son las que procesaron la prueba; la configuración declarativa de consumidores en `backend/agenda/serverless.yml` y `backend/ordenes/serverless.yml` conserva sus mappings nuevos inicialmente **Disabled**. No activar en paralelo los dos pares.
- DynamoDB Streams: no utilizado (adaptación a talleres de SNS de AWS Academy).
- Desde la MV el usuario `voclabs` recibió **explicit deny** en `dynamodb:GetItem`, mientras que invocaciones Lambda con `LabRole` fueron operativas. No modificar IAM ni intentar rodear una restricción del laboratorio; para recuperación, usar flujos autorizados y documentados.

## Próximas tareas para la entrega

1. Frontend React/Amplify conectado a las seis APIs y probando dos tenants. Referenciar `handoff/cloud-project-v2` y el paquete de frontend entregado al equipo.
2. Terminar autorización del técnico asignado, cierre coordinado, faltantes de administración de usuarios y otros eventos de Agenda.
3. Completar carga directa boto3 conforme permisos efectivos del laboratorio, volumen por servicio y tenant, y evidencia sin mensajes de prueba de producción.
4. Pruebas de fallos/duplicados/DLQ, seguridad multitenant, UI móvil y documentación final.
5. Automatización del despliegue sin duplicar SNS/SQS manuales; guardar evidencia de comandos, stacks y recursos finales.

## Handoff a la otra repo

El destino definido por el equipo es `https://github.com/rvcuba-utec/cloud-project-v2`. El código del backend vive aquí, **no** duplicar stacks ni migrar credenciales. Copiar la carpeta `frontend/` del ZIP/paquete de frontend a una rama nueva del repo del equipo, revisar archivos existentes antes de reemplazar, ejecutar `npm install && npm run build` y abrir PR. Las URL API deben verificarse de nuevo al reiniciar AWS Academy.
