# Lambda manual consumidora de Agenda (MS4) — fase SNS/SQS

Código en \`lambda_function.py\` para copiar en la consola AWS Lambda:
\`trazora-agenda-consumidor-dev-manual\` con runtime **Python 3.12** y rol **LabRole**.

## Configuración en la consola

**Por ahora NO activar ningún trigger SQS**. Primero:
1. Configuración → Variables de entorno:
   - \`AGENDA_TABLE\` = \`trazora-agenda-dev\`
   - \`SQS_AGENDA_ARN\` = \`arn:aws:sqs:us-east-1:975050277936:trazora-eventos-agenda-dev\`
2. Code → \`lambda_function.py\`: pegar el código de este directorio y pulsar Deploy.
3. Configuration → Runtime settings: handler \`lambda_function.lambda_handler\`.
4. Configuration → General configuration: timeout **30 segundos**, suficiente para transacciones; cola SQS tiene visibility timeout **180 segundos**.
5. Test → crear evento \`prueba_vacia\` con \`{"Records":[]}\` y verificar \`{"procesados":0,"duplicados":0}\` (no toca DynamoDB).

## Cuando tengamos los 3 componentes preparados

- Confirmar permiso IAM en LabRole para \`dynamodb:GetItem\`, \`dynamodb:TransactWriteItems\` sobre tabla MS4 y \`sqs:ReceiveMessage\`, \`sqs:DeleteMessage\`, \`sqs:GetQueueAttributes\` sobre SQS Agenda, además de logs CloudWatch.
- Añadir trigger **Amazon SQS** que apunte solo a \`trazora-eventos-agenda-dev\`, **batch size 1** (simplifica reintentos). No agregar DLQ como trigger.
- La suscripción SNS debe tener \`Raw message delivery = Enabled\` y filtro \`Message body\` para \`ParteFinalizado\`, como se configuró en la consola.
- Cuando llega un \`ParteFinalizado\`, validar tenant/evento/referencias, buscar visita EN_ATENCION de MS4 y aplicar **una única transacción**: pasar a \`FINALIZADA\`, borrar bloques, restar 1 en CONTROL_ORDEN, guardar \`INBOX#event_id\`. Un reintento con el mismo evento detecta INBOX.
- Tras cinco recepciones fallidas SQS enviará a \`trazora-eventos-agenda-dlq-dev\`; revisar CloudWatch. Las Lambdas SQS procesan al menos una vez y pueden duplicar mensajes.

## Pruebas y advertencias

- El test vacío **solo prueba que importa el código**. No certifica permisos ni finalización de visitas.
- No publicar eventos de negocio hasta que el consumidor de Órdenes esté listo y ambos estén probados.
- La transacción depende de las claves de bloques realmente guardadas en MS4: \`BLOQUE#tecnico_id#YYYY-MM-DDTHH:MM:00Z\`.
- La visita debe estar EN_ATENCION, de la misma orden/tenant y el registro CONTROL_ORDEN debe tener al menos una visita activa.
- Mensajes malformados **no** se eliminan; causan error, reintentos y finalmente DLQ. Esto protege de actualizaciones equivocadas.
- Esta Lambda **no publica VisitaCompletada**; ese es un incremento posterior.
- Esta Lambda está creada manualmente fuera del stack \`trazora-agenda-dev\`. Hay que coordinar su migración declarativa para el curso sin crear recursos duplicados ni destruir mensajes.
- Si se activa la cola antes de limpiar los mensajes ficticios de prueba, estos fallarán validación; se deberá revisar la DLQ y nunca purgar indiscriminadamente.

Archivo solo de apoyo al aprendizaje; revisarlo y probarlo antes de producción.
