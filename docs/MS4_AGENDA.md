# MS4 — Agenda y visitas (primer incremento)

**Estado:** código preparado y versionado en GitHub. No se considera desplegado o validado en AWS hasta que se ejecuten los pasos en EC2.

## Objetivo

Programar una visita para una orden ya creada en MS3, asignándola a un técnico de MS2. Las llamadas de negocio están protegidas por el autorizador de MS0. La función lee el `tenant_id` del contexto autenticado, nunca de campos arbitrarios enviados por el navegador.

## Operaciones implementadas

| Método | Ruta | Resultado |
|---|---|---|
| POST | `/visitas` | Programa visita, HTTP 201 |
| GET | `/visitas?limit=20` | Lista visitas del tenant, paginadas |
| GET | `/visitas/{visita_id}` | Consulta visita o 404 para otra empresa |

Solo pueden operar ADMIN y COORDINADOR en este primer incremento.

### Ejemplo POST /visitas

```json
{
  "orden_id": "<UUID_REAL_DE_MS3>",
  "tecnico_id": "<UUID_REAL_DE_MS2>",
  "inicio": "2026-11-10T15:00:00Z",
  "fin": "2026-11-10T16:00:00Z"
}
```

Las fechas son UTC (sufijo Z). El ejemplo representa 10:00–11:00 en Lima. Las visitas deben comenzar en el futuro, usar intervalos de 30 minutos, tener duración entre 30 minutos y cuatro horas, y empezar/terminar en el mismo día de Lima. El técnico debe estar activo, tener la especialidad requerida por la orden y tener una jornada de MS2 que cubra completamente el intervalo.

### Integración entre servicios

- MS4 → MS3: GET protegido `/ordenes/{orden_id}`, comprueba que pertenece al tenant y está `ABIERTA`.
- MS4 → MS2: GET protegido `/tecnicos/{tecnico_id}`, valida pertenencia, estado y especialidad.
- MS4 → MS2: GET protegido `/tecnicos/{tecnico_id}/jornadas?desde=...&hasta=...` comprueba que el horario está dentro de la jornada.
- MS4 no consulta ni modifica directamente las tablas DynamoDB de MS2 o MS3.

### Datos en `trazora-agenda-dev`

La tabla es exclusiva de MS4, con PK y SK tipo string:

- `TENANT#CLIMALIMA` + `VISITA#uuid`: registro principal.
- `TENANT#CLIMALIMA` + `BLOQUE#uuid-tecnico#fecha-UTC`: bloque de 30 minutos ocupado.
- `TENANT#CLIMALIMA` + `CONTROL_ORDEN#uuid-orden`: contador de visitas activas y control de programación.

**La visita, los bloques y el control se escriben en una sola transacción DynamoDB.** Si un bloque ya está reservado, la transacción falla y devuelve HTTP 409: no queda una visita parcialmente guardada. Este control es la base para implementar bloqueo de cierre de órdenes después.

## Despliegue desde EC2

Las variables nuevas apuntan a las URLs base reales de MS2 y MS3 (terminadas en `/dev`, sin `/tecnicos` o `/ordenes`). MS2 tiene la URL que ya utilizamos en las pruebas. El ARN del autorizador pertenece a MS0.

```bash
cd ~/trazora-fsm
git pull --ff-only
export AWS_PROFILE=default
export AWS_REGION=us-east-1
export LAB_ROLE_ARN=$(aws iam get-role --role-name LabRole --query 'Role.Arn' --output text)
export MS0_AUTHORIZER_ARN=$(aws lambda get-function --function-name trazora-usuarios-dev-validarToken --query 'Configuration.FunctionArn' --output text --region us-east-1)
export MS2_TECNICOS_API_BASE=https://lil6er5i20.execute-api.us-east-1.amazonaws.com/dev

# Completa este valor con el endpoint REAL de MS3 que entregó serverless info:
export MS3_ORDENES_API_BASE=https://ID_REAL_MS3.execute-api.us-east-1.amazonaws.com/dev

cd backend/agenda
python3 -m py_compile handler.py
serverless print --stage dev --region us-east-1
serverless deploy --stage dev --region us-east-1
serverless info --stage dev --region us-east-1
```

**El identificador ID_REAL_MS3 es un marcador, no una URL operativa.** Obtenlo mediante `cd ~/trazora-fsm/backend/ordenes && serverless info --stage dev --region us-east-1`. Si alguna credencial o ARN falla, no continúes el despliegue.

Después verifica en DynamoDB la tabla `trazora-agenda-dev` con estado `Active`.

## Pruebas

Desde la raíz de Trazora:

```bash
python3 scripts/pruebas/probar_ms4.py
```

El programa solicita la URL MS4, autentica administradores de ClimaLima y FríoSur sin imprimir contraseñas/tokens y reutiliza una orden ABIERTA de MS3 y un técnico activo de MS2 con la especialidad requerida. Si hace falta una jornada en una fecha futura que no tenga registro, pide confirmación antes de crearla en MS2. Después pide confirmación antes de programar una visita ficticia.

Pruebas principales: 401 sin token; 201 programación; 200 consulta/listado propios; 404 consulta ajena; 409 al intentar reservar exactamente el mismo bloque; 400 con tenant inyectado.

## Pendiente de implementar antes de la entrega final

- Iniciar, reprogramar, cancelar y finalizar visitas, liberando/actualizando los bloques y el control con transacciones.
- Validación de ausencias, asociación de perfiles técnicos con usuarios MS0, control de versiones e idempotencia de solicitudes.
- Integración de eventos SNS/SQS con MS3 Órdenes y MS5 Partes.
- Disponibilidad enriquecida y conflictos al cambiar jornadas ya reservadas.
- Carga académica de registros con script Python/boto3 desde EC2 (nunca carga masiva por API REST).

No ejecutar `serverless remove` para tratar de solucionar errores: los recursos tienen `DeletionPolicy: Retain` y podrían quedar tablas con datos que requieren administración explícita.
