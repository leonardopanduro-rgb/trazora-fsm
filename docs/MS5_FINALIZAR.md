# MS5 — Finalizar parte y registrar evento OUTBOX (incremento 2)

**Rama:** \`feature/ms5-finalizar-parte-outbox-2026-11-04\`  
**Estado de implementación:** código y tests preparados en GitHub. No implica que la Lambda ya esté desplegada ni que SNS/SQS procese eventos.

## Objetivo

Finalizar un parte de visita **EN_ATENCION** sin permitir duplicaciones, conservar el diagnóstico/evidencia y registrar \`ParteFinalizado\` como un evento \`OUTBOX\` **en la misma transacción DynamoDB** que cambia el parte de \`BORRADOR\` a \`FINALIZADO\`.

**Importante:** el registro \`OUTBOX\` **NO equivale a publicación en SNS**. En esta etapa no existe un publicador ni consumidores SQS, así que MS4 y MS3 **NO se actualizan automáticamente**. Los registros de eventos quedan pendientes para implementar la arquitectura EDA y su mecanismo de recuperación después.

## Endpoint nuevo

\`\`\`http
POST /partes/{parte_id}/finalizar
Authorization: Bearer <token-por-MS0>
Content-Type: application/json

{"version": 2}
\`\`\`

La \`version\` debe ser la obtenida de \`GET /partes/{parte_id}\`; no se debe asumir que sea siempre 2. Si se editó el parte entre la consulta y la finalización, devuelve 409.

**Requisitos para finalizar:**

- Sesión de ADMIN o COORDINADOR del mismo tenant, autenticada por MS0.
- Parte \`BORRADOR\`, con diagnóstico no vacío, al menos una tarea registrada y resultado distinto de \`PENDIENTE\`.
- Visita del mismo tenant y orden, verificada por API protegida de MS4, con \`estado=EN_ATENCION\`.
- Como mínimo **una evidencia \`CONFIRMADA\`** para ese parte en la tabla de MS5 (se inspeccionan todas las páginas de resultados). Las evidencias pendientes no cuentan como confirmadas.
- La operación tiene una condición sobre el estado y la versión; reintentos con parte ya \`FINALIZADO\` devuelven \`200 sin_cambios=true\` y no insertan otro evento.

**HTTP:**

- \`200\`: parte finalizado, respuesta incluye \`parte\`, \`sin_cambios\`, \`evento.event_id\`, \`evento.event_type=ParteFinalizado\`, \`evento.estado=PENDIENTE_PUBLICACION\`.
- \`400\`: body inválido, campos extras o \`version\` no entero positivo.
- \`401\`/\`403\`: autorización o rol no permitido.
- \`404\`: parte/visita inexistente o de otro tenant.
- \`409\`: estado o versión incompatible, o transacción concurrente.
- \`422\`: falta diagnóstico, tareas, resultado o evidencia confirmada.
- \`502\`/\`503\`: no se pudo consultar MS4 / evidencias.
- \`500\`: error inesperado al guardar la transacción.

## OUTBOX por tenant

Ejemplo del nuevo ítem en \`trazora-partes-dev\`:

\`\`\`json
{
  "PK": "TENANT#CLIMALIMA",
  "SK": "OUTBOX#<event_id>",
  "entity_type": "OUTBOX",
  "tenant_id": "CLIMALIMA",
  "event_id": "<uuid>",
  "event_type": "ParteFinalizado",
  "estado": "PENDIENTE",
  "creado_en": "<fecha UTC>",
  "payload": {
    "event_id": "<uuid>",
    "event_type": "ParteFinalizado",
    "schema_version": 1,
    "tenant_id": "CLIMALIMA",
    "aggregate_type": "PARTE",
    "aggregate_id": "<parte_id>",
    "aggregate_version": 3,
    "occurred_at": "<fecha UTC>",
    "correlation_id": "<visita_id>",
    "data": {
      "visita_id": "<visita_id>",
      "orden_id": "<orden_id>",
      "parte_id": "<parte_id>",
      "resultado": "RESUELTO"
    }
  }
}
\`\`\`

\`event_type\` está **en el cuerpo JSON** para ser compatible con el stack de SNS/SQS que ya utiliza \`FilterPolicyScope: MessageBody\`. En la siguiente fase el publicador DynamoDB Streams/SNS debe enviar \`payload\` como \`Message\`, con manejo de reintentos y recuperación de OUTBOX pendientes anteriores a la activación del stream.

Al contar los **30 000 registros académicos por microservicio**, los ítems \`OUTBOX\` no deben considerarse registros principales de negocio.

## Qué falta para tener finalización END-TO-END

- Publicador de \`OUTBOX\` mediante Streams + recuperación de eventos anteriores y manejo de reintentos.
- Consumidor de Agenda (SQS) que cambie la visita \`EN_ATENCION\` a \`FINALIZADA\` y libere bloques/decremente control exactamente una vez, usando INBOX transaccional.
- Consumidor de Órdenes (SQS) que registre el resultado, actualice estados y evite cierres inconsistentes.
- Validación de cuentas \`TECNICO\` y relación entre usuario MS0 y técnico asignado MS2. **Por ahora finalización solo ADMIN/COORDINADOR**, igual que el resto del primer incremento.
- Resolver correctamente carreras entre iniciar/reprogramar/cancelar una visita y finalizar su parte. Mientras no existan consumidores, una visita iniciada seguirá \`EN_ATENCION\` aunque el parte esté \`FINALIZADO\`.
- Compatibilidad total de \`pedir_carga\` y \`confirmar_carga\` con finalizaciones concurrentes; en este incremento se comprueba que haya al menos una evidencia confirmada, sin asumir que toda evidencia pendiente ya se ha cargado.

## Prueba y despliegue en EC2

Cambiar a esta rama (primero \`git status\` para detectar cambios no confirmados):

\`\`\`bash
cd ~/trazora-fsm
git fetch origin
git switch --track origin/feature/ms5-finalizar-parte-outbox-2026-11-04

python3 -m py_compile backend/partes/handler.py scripts/pruebas/probar_ms5_finalizar.py
python3 -m unittest discover -s tests -p 'test_ms5_finalizar.py' -v
python3 -m unittest discover -s tests -p 'test_ms5_json.py' -v
\`\`\`

Antes de desplegar, preparar la sesión AWS Academy (\`aws sts get-caller-identity\`), \`LAB_ROLE_ARN\`, \`MS0_AUTHORIZER_ARN\` y \`MS4_AGENDA_API_BASE\`. El stack MS5 ya existe; el despliegue añade una sola Lambda y método HTTP a ese stack:

\`\`\`bash
export AWS_PROFILE=default
export AWS_REGION=us-east-1
export LAB_ROLE_ARN=$(aws iam get-role --role-name LabRole --query 'Role.Arn' --output text)
export MS0_AUTHORIZER_ARN=$(aws lambda get-function --function-name trazora-usuarios-dev-validarToken --query 'Configuration.FunctionArn' --output text --region us-east-1)
export MS4_AGENDA_API_BASE=https://4o2ucd2ati.execute-api.us-east-1.amazonaws.com/dev

cd ~/trazora-fsm/backend/partes
serverless print --stage dev --region us-east-1
serverless deploy --stage dev --region us-east-1
serverless info --stage dev --region us-east-1
\`\`\`

### Prueba interactiva: cuidado, es irreversible en ese parte

\`\`\`bash
cd ~/trazora-fsm
python3 scripts/pruebas/probar_ms5_finalizar.py
\`\`\`

El script exige la confirmación **FINALIZAR** y trabaja solo con visitas \`EN_ATENCION\`, con token del tenant. Si no hay visita iniciada, se puede crear una desde \`probar_ms4_ciclo.py\` respondiendo \`SI\` a la última pregunta. El script puede **crear un parte de prueba, editarlo y cargar una imagen PNG de 1 píxel** en S3 únicamente si das tu confirmación.

Después de finalizar, **MS4 todavía seguirá EN_ATENCION** hasta el siguiente incremento EDA. No se deben reutilizar partes de negocio reales para esta prueba. No ejecutar \`serverless remove\` ni borrar tablas para limpiar los registros de prueba.
