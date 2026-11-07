# Lambda consumidora SQS Órdenes MS3 — creada manualmente desde AWS

**Archivo:** \`lambda_function.py\` (copiar íntegro en AWS Lambda).
**Función:** \`trazora-ordenes-consumidor-dev-manual\`; Python 3.12; handler \`lambda_function.lambda_handler\`.

## Configurar desde AWS Lambda

En **Configuration → Environment variables**:

| Clave | Valor |
|---|---|
| \`ORDENES_TABLE\` | \`trazora-ordenes-dev\` |
| \`SQS_ORDENES_ARN\` | \`arn:aws:sqs:us-east-1:975050277936:trazora-eventos-ordenes-dev\` |

Verificar **Configuration → General configuration**: timeout **30 segundos**, 128 MB; rol existente \`LabRole\`. La cola debe tener timeout de visibilidad **180 segundos**, y DLQ configurada a **5 recepciones**.

Probar desde **Test** con \`{"Records":[]}\`. Resultado esperado:
\`{"procesados":0,"duplicados":0}\`. **Este test vacío no demuestra permisos ni escritura en DynamoDB.**

**NO AÑADIR TRIGGER SQS todavía**, ni probar con un evento real inventado. Se requiere verificar el IAM de LabRole, estado de la cola y las otras dos Lambdas antes de procesar órdenes reales.

## Contrato y resultado de negocio

La suscripción SNS a \`trazora-eventos-ordenes-dev\` filtra por \`event_type\` en el **cuerpo JSON**; *Raw message delivery* habilitado. Este primer consumidor admite **solamente** \`ParteFinalizado\` emitido por MS5; los demás eventos del filtro se habilitarán progresivamente cuando existan publicadores y contratos completos.

Para un evento válido se realizan juntas tres escrituras DynamoDB \`trazora-ordenes-dev\`:
1. \`ORDEN#<orden_id>\`: se actualizan los campos \`estado\`, \`ultimo_resultado\`, \`ultimo_parte_id\`, \`ultima_visita_id\`, \`ultimo_evento_ocurrido_en\`, \`requiere_revisita\`.
2. \`HISTORIAL#<orden_id>#<event_id>\`: conserva información del resultado y la transición.
3. \`INBOX#<event_id>\`: guarda hash SHA-256 del contenido para detectar entregas duplicadas; ante duplicado idéntico no aplica cambios nuevamente.

**Política de estado intencional:**
- \`RESUELTO\` → \`PENDIENTE_DE_CIERRE\`; **NO significa CERRADA**. Verificar MS4 y controles de agenda antes de agregar \`cerrar\`.
- \`REQUIERE_REVISITA\` o \`NO_ATENDIDO\` → estado \`ABIERTA\` y \`requiere_revisita=true\`, para que MS4 pueda programar otra visita; el resultado se conserva.
- Orden \`CERRADA\`/\`CANCELADA\`: rechazar un evento tardío; revisar mensajes en DLQ, no reabrir.
- Se comprueba fecha del evento para evitar sobrescribir eventos más recientes.

\`GET /ordenes/{orden_id}\` actual solo devuelve los campos antiguos; **los nuevos campos aparecen en DynamoDB, pero la API aún debe actualizarse** para mostrarlos en frontend o en las respuestas de MS3. No declarar completa la integración hasta realizar ese ajuste.

## Seguridad y consistencia

- Se validan UUIDs, tipo, versión del esquema, empresa, correlación, resultado y fecha.
- La PK de acceso usa el tenant contenido en un evento filtrado por SNS/SQS; el código verifica además tenant e ID de la orden y ejecuta actualización condicional.
- La integridad de origen depende también de la política de acceso de la cola (debería permitir publicaciones del SNS específico, no cualquier principal); validar antes de activar el trigger.
- Si DynamoDB falla, la Lambda lanza excepción y SQS reintentará el mensaje. Con batch size **1**, no se descartan otros mensajes buenos del mismo lote.
- Para no bloquear las futuras revisitas, el estado de la orden se conserva \`ABIERTA\` cuando el resultado no es RESUELTO, porque MS4 actualmente solo permite programar en órdenes ABIERTA.
- **Pendiente:** si en el futuro hay múltiples partes para una misma orden, ajustar las reglas de secuencia y cierre tras consumidor MS4. Los dos consumidores son asíncronos y su orden de ejecución no está garantizado.

## Trabajo restante

1. Validar la Lambda sin datos con \`Records: []\`.
2. Confirmar permisos IAM SQS, DynamoDB TransactWriteItems/GetItem y CloudWatch.
3. Revisar y probar las tres Lambdas y el contrato del evento MS5 antes de activar triggers.
4. Añadir trigger SQS a MS3 y MS4 con lote de **1**.
5. Activar DynamoDB Streams en MS5, conectar publicador y recuperar OUTBOX antiguos en forma segura.
6. Probar CLIMALIMA/FRIOSUR, mensajes duplicados, errores, DLQ y actualizar API GET MS3 para exponer nuevos campos.
7. Versionar IaC para recursos manuales sin intentar crearlos otra vez; el curso exige Serverless Framework.
