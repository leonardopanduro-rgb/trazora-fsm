# MS3 Órdenes de trabajo — primer incremento

## Estado

El código queda preparado en GitHub. El despliegue real de MS3 debe ejecutarse desde EC2 con credenciales AWS Academy vigentes. MS0, MS1 y MS2 ya tienen pruebas de integración positivas informadas por el equipo.

## Qué hace MS3

- **POST /ordenes**: crea una orden de servicio `ABIERTA` únicamente para el tenant autenticado, **después de consultar MS1 Clientes** mediante su API protegida.
- **GET /ordenes?limit=20**: lista órdenes paginadas de la empresa del token.
- **GET /ordenes/{orden_id}**: consulta una orden, o devuelve 404 cuando no pertenece al tenant autenticado.
- Todas las rutas exigen `Authorization: Bearer <TOKEN_MS0>` y rol `ADMIN` o `COORDINADOR`.
- Una Lambda de MS3 **no lee ni escribe** directamente en la tabla de DynamoDB de MS1. Recibe `tenant_id` y `usuario_id` del autorizador de MS0 y consulta MS1 por HTTPS reenviando el token de la sesión.

## Datos aceptados

Ejemplo de `POST /ordenes` con token válido:

```json
{
  "cliente_id": "<UUID_REAL_DE_UN_CLIENTE>",
  "tipo_servicio": "REPARACION",
  "descripcion": "El aire acondicionado de la oficina no enfría",
  "prioridad": "ALTA"
}
```

Los valores admitidos para tipo_servicio son `INSTALACION`, `MANTENIMIENTO` y `REPARACION`. Prioridad admite `BAJA`, `MEDIA` y `ALTA` (por defecto MEDIA). El backend genera `orden_id`, `estado=ABIERTA`, `creada_en`, `creada_por` y `tenant_id`. No acepta estos campos en el JSON.

Si el cliente no pertenece a esa empresa, devuelve **404** y no crea una orden. Si MS1 no responde, devuelve 502. Una respuesta 200 de MS1 se verifica nuevamente comparando el ID, tenant y el estado activo del cliente antes de guardar.

## Tabla

`trazora-ordenes-dev` (DynamoDB propia de MS3):

- `PK = TENANT#CLIMALIMA`
- `SK = ORDEN#<UUID>`

**Nota:** esta primera versión no soporta todavía ubicación, visitas, estados derivados de eventos, cierre, cancelación, historiales ni idempotencia por identificador de solicitud; los iremos incorporando con MS4 Agenda y MS5 Partes. El MVP inicial se limita a crear, listar y consultar órdenes.

## Cómo desplegar desde EC2

En la terminal de Ubuntu:

```bash
cd ~/trazora-fsm
git status
git pull --ff-only

export AWS_PROFILE=default
export AWS_REGION=us-east-1
export LAB_ROLE_ARN=$(aws iam get-role --role-name LabRole --query 'Role.Arn' --output text)
export MS0_AUTHORIZER_ARN=$(aws lambda get-function --function-name trazora-usuarios-dev-validarToken --query 'Configuration.FunctionArn' --output text --region us-east-1)

# MS1 existente, autorizado y previamente probado:
export MS1_CLIENTES_API_BASE=https://9qksceoae2.execute-api.us-east-1.amazonaws.com/dev

cd backend/ordenes
python3 -m py_compile handler.py
serverless print --stage dev --region us-east-1
serverless deploy --stage dev --region us-east-1
serverless info --stage dev --region us-east-1
```

Antes de desplegar, comprueba que los ARN son válidos y que la cuenta y región son las mismas del laboratorio. `MS1_CLIENTES_API_BASE` debe terminar en `/dev`, **no en `/clientes`**. El backend usa esa URL base para hacer `GET /clientes/<cliente_id>`.

Revisa en DynamoDB que `trazora-ordenes-dev` tenga estado `Active`.

## Prueba automática desde EC2

```bash
cd ~/trazora-fsm
python3 scripts/pruebas/probar_ms3.py
```

El script solicita la URL real de MS3 que devolvió `serverless info`, autentica a los administradores de ClimaLima y FríoSur de forma interactiva, recupera un cliente existente de ClimaLima desde MS1 y **pide confirmación antes de crear una orden de prueba**. Nunca muestra claves ni tokens. Al final cierra ambas sesiones.

Debe validar: 401 sin token; 201 al crear con cliente válido; 200 al consultar y listar; 404 al intentar ver una orden de otra empresa; 400 si el JSON pretende cambiar `tenant_id`; 404 al utilizar un cliente inexistente o ajeno. No utilizar API REST para la carga masiva exigida en el curso: esa carga debe hacerse después con Python/boto3 desde la MV.
