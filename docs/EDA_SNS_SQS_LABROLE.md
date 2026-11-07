> **Actualización validada el 07/11/2026:** se comprobó en AWS Academy un flujo end-to-end real: `ParteFinalizado` → SNS → SQS → Agenda `FINALIZADA` → Órdenes `PENDIENTE_DE_CIERRE`. Los dos consumidores **manuales** están habilitados en dev. La descripción de abajo refleja el plan previo a la prueba; ver [estado y evidencia actual](ESTADO_INTEGRACION_2026-11-07.md). El despliegue declarativo completo y las pruebas de duplicados/DLQ siguen pendientes.

# EDA de Trazora en AWS Academy: SNS + SQS + Lambda, sin Streams

**Rama de código:** feature/eda-sns-sqs-academy-2026-11-06.
**Estado:** preparado en GitHub. Estos cambios NO han sido desplegados ni probados en tu cuenta AWS.

## Base exclusiva de los talleres

- Semana 13, Taller 1 de SNS, diapositiva 13: publicar JSON desde Lambda con boto3 y sns.publish.
- Semana 13, Taller 2 de SNS: evento que activa una Lambda y entrega a SNS.
- Semana 11, Taller 4 de Serverless: configuración por stage y despliegue automatizado.
- Semana 12, Taller CloudWatch: registros INFO/ERROR.
- La transcripción del proyecto exige SNS/SQS y microservicios multitenant.

NO se utilizan DynamoDB Streams. Como SNS Publish ocurre después de guardar
una transacción, OUTBOX conserva eventos pendientes y el script Python/boto3
permite reintentar. INBOX impide aplicar efectos duplicados.

## Estado confirmado antes de estos cambios

En us-east-1 existen MS0–MS5, un tema SNS, dos colas SQS y dos DLQ.
No existe el stack trazora-eventos-dev, pero sus recursos homónimos sí existen
fuera de él. Las Lambdas consumidoras con sufijo -manual estaban Active,
pero sus mappings SQS estaban Disabled (USER_INITIATED).

**NO desplegar infra/eventos/serverless.yml en esta cuenta:** intentaría
crear SNS/SQS con nombres que ya existen. Conservamos la plantilla como
referencia para una cuenta limpia o futura importación controlada.

## Flujo de esta rama

1. MS5 confirma parte + OUTBOX ParteFinalizado en una transacción y luego SNS Publish.
2. Si SNS falla, el OUTBOX queda PENDIENTE y puede recuperarse; el parte sigue FINALIZADO.
3. SNS entrega ParteFinalizado a las colas SQS de MS4 y MS3.
4. MS3 registra el resultado en HISTORIAL + INBOX, sin adelantar el estado de la orden.
5. MS4 transacciona FINALIZADA + bloques liberados + contador -1 + INBOX + OUTBOX VisitaCompletada.
6. MS4 publica VisitaCompletada a SNS; si falla, reintenta por SQS o recuperador OUTBOX.
7. MS3 procesa VisitaCompletada y cambia la orden: RESUELTO -> PENDIENTE_DE_CIERRE, otros -> ABIERTA.
8. La misma identidad event_id se procesa una sola vez por consumidor.

ATENCION: el filtro real de SNS para Órdenes incluye actualmente también
VisitaProgramada, VisitaReprogramada, VisitaIniciada y VisitaCancelada. En esta
rama el consumidor solo admite ParteFinalizado y VisitaCompletada. Antes de
activarlo se debe actualizar el filtro REAL a esos dos tipos o implementar
y probar los contratos de los demás eventos. Cambiar el YAML no modifica
el filtro SNS ya configurado manualmente.

Pendientes del producto: autorización a TECNICO asignado en MS5, productores
de los otros eventos Agenda, cierre/cancelación coordinada y frontend.

## 1. Pruebas locales primero (SIN AWS)

~~~bash
cd ~/trazora-fsm
git status --short
# Revisar cambios locales si los hay; no perderlos.
git fetch origin
git switch --track origin/feature/eda-sns-sqs-academy-2026-11-06

VENV="$HOME/.venvs/trazora-tools"
test -x "$VENV/bin/python" || python3 -m venv "$VENV"
"$VENV/bin/python" -c "import boto3,botocore" || "$VENV/bin/python" -m pip install boto3

PYTHONDONTWRITEBYTECODE=1 "$VENV/bin/python" -m unittest discover -s tests -p 'test_eda_*.py' -v
PYTHONDONTWRITEBYTECODE=1 "$VENV/bin/python" -m unittest discover -s tests -p 'test_ms5_finalizar.py' -v
PYTHONDONTWRITEBYTECODE=1 "$VENV/bin/python" -m unittest discover -s tests -p 'test_*.py' -v
~~~

Las nuevas pruebas usan mocks y no contactan AWS. Su resultado aún no está confirmado.

## 2. Preflight solo lectura y Serverless print

~~~bash
export AWS_PAGER=""
export AWS_REGION=us-east-1
aws sts get-caller-identity --region "$AWS_REGION" --output json
export LAB_ROLE_ARN="$(aws iam get-role --role-name LabRole --query Role.Arn --output text)"
export CUENTA="$(aws sts get-caller-identity --query Account --output text)"
export TRAZORA_EVENTOS_TOPIC_ARN="arn:aws:sns:us-east-1:$CUENTA:trazora-fsm-eventos-dev"
export TRAZORA_SQS_AGENDA_ARN="arn:aws:sqs:us-east-1:$CUENTA:trazora-eventos-agenda-dev"
export TRAZORA_SQS_ORDENES_ARN="arn:aws:sqs:us-east-1:$CUENTA:trazora-eventos-ordenes-dev"
export MS0_AUTHORIZER_ARN="$(aws lambda get-function --function-name trazora-usuarios-dev-validarToken --query Configuration.FunctionArn --output text)"

# Reutilizar URLs internas de las Lambdas existentes:
export MS1_CLIENTES_API_BASE="$(aws lambda get-function-configuration --function-name trazora-ordenes-dev-crear --query Environment.Variables.CLIENTES_API_BASE --output text)"
export MS3_ORDENES_API_BASE="$(aws lambda get-function-configuration --function-name trazora-agenda-dev-programar --query Environment.Variables.ORDENES_API_BASE --output text)"
export MS2_TECNICOS_API_BASE="$(aws lambda get-function-configuration --function-name trazora-agenda-dev-programar --query Environment.Variables.TECNICOS_API_BASE --output text)"
export MS4_AGENDA_API_BASE="$(aws lambda get-function-configuration --function-name trazora-partes-dev-finalizar --query Environment.Variables.AGENDA_API_BASE --output text)"

aws sns get-topic-attributes --topic-arn "$TRAZORA_EVENTOS_TOPIC_ARN" --query 'Attributes.TopicArn' --output text
(cd backend/ordenes && serverless print --stage dev --region us-east-1)
(cd backend/agenda && serverless print --stage dev --region us-east-1)
(cd backend/partes && serverless print --stage dev --region us-east-1)
~~~

Verificar que ninguna variable sea None. La confianza de LabRole NO prueba por
sí sola permiso SNS Publish, transacciones o cambios de event source mappings.

## 3. Despliegue posterior, pendiente de pruebas y revisión

1. Desplegar MS3 y MS4 por Serverless; crear nuevas Lambdas y mappings Disabled.
2. Mantener las dos Lambdas con sufijo -manual y sus mappings Disabled.
3. Revisar el filtro SNS real, limitarlo a los dos tipos implementados.
4. Desplegar MS5 con el ARN del tema.
5. Preparar registros de prueba y habilitar SOLO los mappings nuevos tras verificar sus UUID.
6. Probar flujo extremo a extremo, CloudWatch, INBOX, OUTBOX, DLQ, y doble entrega.
7. Si hay un error, deshabilitar los mappings nuevos y revisar los mensajes. No ejecutar serverless remove ni borrar tablas/colas.

## 4. Consulta de eventos pendientes (dry-run; no publica)

~~~bash
"$HOME/.venvs/trazora-tools/bin/python" scripts/recovery/publicar_outbox.py --servicio partes --tenant CLIMALIMA --stage dev --max 10
"$HOME/.venvs/trazora-tools/bin/python" scripts/recovery/publicar_outbox.py --servicio agenda --tenant CLIMALIMA --stage dev --max 10
~~~

Publicar requeriría además --apply --confirm PUBLICAR. No ejecutar esa
opción sin revisar destino y eventos de prueba. Puede haber retransmisiones
con el mismo event_id si SNS publicó y falló la marca; INBOX las controla.
