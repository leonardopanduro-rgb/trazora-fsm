# Eventos Trazora FSM — etapa 1: infraestructura SNS/SQS

**Situación actual:** MS0–MS5 tienen una base funcional probada. Los borradores de MS5 NO se finalizan aún ni actualizan automáticamente Agenda/Órdenes. Este incremento solo prepara la infraestructura declarativa de mensajería; no añade publicadores ni consumidores.

## Flujo previsto

```text
MS5 ParteFinalizado (en etapa posterior)
     -> evento persistido OUTBOX en su tabla
     -> DynamoDB Streams + Lambda publicadora (pendiente)
     -> SNS trazora-fsm-eventos-dev
           -> SQS Agenda (solo ParteFinalizado)
           -> SQS Órdenes (ParteFinalizado + eventos de Agenda)
     -> Lambdas consumidoras con idempotencia y cambios de estado (pendientes)
```

No equiparar publicar un evento con finalizar una visita o cerrar la orden. Los consumidores todavía no están implementados. La entrega final necesita que los cambios de MS4 y MS3 realmente ocurran y se puedan demostrar.

## Recursos que despliega `infra/eventos/serverless.yml`

- Tema SNS por stage: `trazora-fsm-eventos-dev`.
- SQS de Agenda: `trazora-eventos-agenda-dev`.
- SQS de Órdenes: `trazora-eventos-ordenes-dev`.
- DLQ de Agenda y DLQ de Órdenes, retención de 14 días.
- Políticas SQS que autorizan **solo** `sqs:SendMessage` desde ese tema SNS.
- Dos suscripciones SNS que filtran el campo JSON `event_type` del cuerpo con `FilterPolicyScope: MessageBody`. Entrega raw para que el consumidor reciba el JSON del evento sin sobre SNS.

Las colas principales retienen mensajes hasta 4 días; tras 5 recepciones fallidas, un mensaje se enviaría a la DLQ correspondiente. Tienen cifrado SQS administrado y un timeout de visibilidad de 180 segundos. En esta etapa no hay Lambdas consumidoras, así que **no publiques eventos reales**: no serán procesados, aunque se guarden temporalmente en SQS.

## Contrato inicial del evento (para implementar en la siguiente etapa)

```json
{
  "event_id": "UUID_DEL_EVENTO",
  "event_type": "ParteFinalizado",
  "schema_version": 1,
  "tenant_id": "CLIMALIMA",
  "aggregate_type": "PARTE",
  "aggregate_id": "UUID_DEL_PARTE",
  "aggregate_version": 1,
  "occurred_at": "2026-11-10T16:05:00Z",
  "correlation_id": "ATENCION-VIS-001",
  "data": {
    "visita_id": "UUID_DE_VISITA",
    "orden_id": "UUID_DE_ORDEN",
    "parte_id": "UUID_DEL_PARTE",
    "resultado": "RESUELTO"
  }
}
```

Es un **contrato propuesto** coherente con el plan del proyecto. Debe validarse en los consumidores. Los mensajes de SNS deben incluir `event_type` dentro del cuerpo JSON para que funcionen los filtros; no basta con asignarlo como atributo externo.

## Despliegue en EC2

1. Inicia AWS Academy y verifica credenciales temporales del laboratorio. No subas credenciales a GitHub.
2. En Ubuntu:

```bash
cd ~/trazora-fsm
git status
git pull --ff-only
export AWS_PROFILE=default
export AWS_REGION=us-east-1
aws sts get-caller-identity --region us-east-1
export LAB_ROLE_ARN=$(aws iam get-role --role-name LabRole --query 'Role.Arn' --output text)

cd infra/eventos
serverless print --stage dev --region us-east-1
serverless deploy --stage dev --region us-east-1
```

El `serverless.yml` gestiona recursos compartidos sin funciones Lambda. El stack esperado es `trazora-eventos-dev`. Requiere permisos de CloudFormation, SNS y SQS habilitados en AWS Academy; si sale `AccessDenied`, no lo eludas creando usuarios IAM de administrador.

## Comprobar el resultado

```bash
aws cloudformation describe-stacks \
  --stack-name trazora-eventos-dev \
  --region us-east-1 \
  --query 'Stacks[0].Outputs' \
  --output table

aws sqs list-queues --queue-name-prefix trazora-eventos- --region us-east-1
aws sns list-topics --region us-east-1
```

También puedes verificar visualmente SNS → Topics y SQS → Queues en `us-east-1`. Debe haber un tema, dos colas principales y dos DLQ.

## Pendiente después de validar esta infraestructura

- Implementar `POST /partes/{parte_id}/finalizar` con validaciones, outbox transaccional y un evento único por parte.
- Activar DynamoDB Streams y crear publicador autorizado a SNS con recuperación de eventos pendientes.
- Implementar consumidores con INBOX/idempotencia que actualicen MS4 y MS3; reservar/terminar visitas sin romper control de bloques.
- Pruebas end-to-end de un `ParteFinalizado`, incluyendo reintentos, fallos, duplicados y aislamiento multitenant.
- Más adelante: datos ficticios masivos por Python/boto3 y frontend React en Amplify.

**No ejecutes `serverless remove` sin revisar recursos/colas y mensajes:** podría eliminar infraestructura usada por el proyecto. No se han modificado las Lambdas MS0–MS5 en esta etapa.
