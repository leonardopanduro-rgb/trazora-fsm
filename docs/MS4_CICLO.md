# MS4 — Ciclo de visitas: iniciar, reprogramar y cancelar (incremento 2)

**Rama de trabajo:** \`feature/ms4-ciclo-visitas-2026-11-04\`; incluye los cambios validados de MS2. **Este código aún no se ha confirmado desplegado en AWS**.

## Rutas nuevas

Todas requieren token de MS0 (ADMIN/COORDINADOR); \`tenant_id\` se toma del autorizador y no del body.

| Método | Ruta | Body exacto | Qué responde |
|---|---|---|---|
| POST | \`/visitas/{visita_id}/iniciar\` | \`{}\` | 200 con visita \`EN_ATENCION\` |
| PATCH | \`/visitas/{visita_id}/reprogramar\` | \`{"tecnico_id":"UUID","inicio":"UTC_Z","fin":"UTC_Z"}\` | 200 con visita \`PROGRAMADA\`, nuevo horario, versión |
| POST | \`/visitas/{visita_id}/cancelar\` | \`{}\` | 200 con visita \`CANCELADA\`; libera bloques y descuenta visita activa |
| GET | \`/tecnicos/{tecnico_id}/reservas-futuras\` | — | 200 con \`tiene_reservas\`, usado por MS2 |

- \`401\` token inválido, \`403\` rol sin permiso, \`404\` visita ajena o no encontrada, \`400\` JSON/ID/formato inválido, \`409\` solapamiento, cambio concurrente o transición no permitida.
- Se añade \`version\` al registro de visitas; las visitas antiguas creadas sin ese campo siguen siendo compatibles con \`attribute_not_exists(version)\`.
- \`iniciar\` acepta solo \`PROGRAMADA\` y deja bloques y control de orden ocupados: finalización real mediante MS5/SNS/SQS viene después. Una segunda llamada sobre \`EN_ATENCION\` devuelve \`200 sin_cambios=true\`.
- \`reprogramar\` acepta solo \`PROGRAMADA\`; valida orden ABIERTA y técnico activo/especialidad/jornada mediante API de MS3/MS2, y horarios futuros de 30 minutos. Eliminar y crear bloques ocurre **en una transacción DynamoDB** junto con actualizar la visita. Un bloque compartido entre horario viejo/nuevo se conserva sin doble Put/Delete. La cuenta de visitas activas **no cambia**. Si la orden está bloqueada, devuelve 409.
- \`cancelar\` acepta solo \`PROGRAMADA\`: en una transacción cambia estado, elimina todos sus bloques (condicionados a que pertenezcan a esa visita) y decrementa el marcador \`visitas_activas\` una vez. Repetirlo sobre \`CANCELADA\` devuelve \`200 sin_cambios=true\`.
- No hay \`POST /visitas/{id}/finalizar\` por ahora: se implementará con consumidor SQS cuando MS5 publique \`ParteFinalizado\`. No cerrar orden por cancelar una única visita.
- **Limitación conocida:** aún no se bloquea la reprogramación/cancelación de una visita que tenga un borrador MS5 asociado; habrá que coordinar esa validación al implementar la finalización y el evento. La programación y el cambio de estado de MS2 tampoco son una transacción distribuida, por lo que queda una carrera extrema para resolver.
- **Decisión temporal para demo:** la transición \`iniciar\` se controla por estado, sin impedir que un coordinador la inicie antes de su hora programada. Reforzar con política horaria cuando exista el flujo para técnicos.

## Pre-requisitos de despliegue

La EC2 usa rama nueva, AWS_PROFILE=default, región us-east-1, Serverless Framework v4 y los ARN/URLs de etapa \`dev\`:

\`\`\`bash
cd ~/trazora-fsm
git fetch origin
git switch --track origin/feature/ms4-ciclo-visitas-2026-11-04

export AWS_PROFILE=default
export AWS_REGION=us-east-1
export LAB_ROLE_ARN=$(aws iam get-role --role-name LabRole --query 'Role.Arn' --output text)
export MS0_AUTHORIZER_ARN=$(aws lambda get-function --function-name trazora-usuarios-dev-validarToken --query 'Configuration.FunctionArn' --output text --region us-east-1)
export MS3_ORDENES_API_BASE=https://ul25x5oe02.execute-api.us-east-1.amazonaws.com/dev
export MS2_TECNICOS_API_BASE=https://lil6er5i20.execute-api.us-east-1.amazonaws.com/dev

python3 -m py_compile backend/agenda/handler.py scripts/pruebas/probar_ms4_ciclo.py
python3 -m unittest discover -s tests -p 'test_ms4_ciclo.py' -v
python3 -m unittest discover -s tests -p 'test_ms4_reservas.py' -v
\`\`\`

En sesión Python 3.10 de Ubuntu, \`ZoneInfo("America/Lima")\` requiere base horaria disponible. Los tests no invocan AWS.

Si pasan pruebas locales y tienes credenciales válidas, despliega **solo MS4 Agenda**:

\`\`\`bash
cd ~/trazora-fsm/backend/agenda
serverless print --stage dev --region us-east-1
serverless deploy --stage dev --region us-east-1
serverless info --stage dev --region us-east-1
\`\`\`

No cambia las tablas MS0/MS2/MS3/MS5 ni SNS/SQS; reutiliza \`trazora-agenda-dev\` y sus reservas actuales. Las API Gateway pueden tardar un momento en reflejar nuevas rutas.

## Prueba real controlada

Desde raíz:

\`\`\`bash
cd ~/trazora-fsm
python3 scripts/pruebas/probar_ms4_ciclo.py
\`\`\`

Cuando pida URL, pegar la **misma base MS4** comprobada en \`serverless info\` (antes \`https://4o2ucd2ati.execute-api.us-east-1.amazonaws.com/dev\`). Login con admins CLIMALIMA y FRIOSUR; contraseñas ocultas. Se creará una nueva jornada solo con \`SI\`, y una visita nueva solo con \`SI\`; la prueba la reprogramará y cancelará, liberando los bloques. Opcionalmente puede crear e iniciar **otra** visita que quedará EN_ATENCION para usar en MS5: ese cambio no se revierte automáticamente, por lo que debe ser voluntario.

Si una visita de prueba no llega a cancelarse, conservar el ID y no repetir masivamente el script.

## Pruebas y limitaciones pendientes

- Casos reales de conflicto de bloques, cambio de técnico y cancelación repetida.
- Coordinación entre MS4 y MS5 cuando exista parte BORRADOR.
- Gestión de ausencias de MS2, bloqueo de orden, evento \`VisitaCompletada\` y finalización con SQS.
- No borrar ni recrear la tabla \`trazora-agenda-dev\` para resolver errores: \`DeletionPolicy: Retain\`.
