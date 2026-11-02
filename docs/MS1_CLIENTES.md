# MS1 Clientes — primer incremento

Código e infraestructura preparados en GitHub, **todavía no desplegados en AWS**.

## Contrato

- `POST /clientes`: crea un cliente con body JSON `{"nombre":"Comercial López","correo":"contacto@example.com","telefono":"999111222"}`; devuelve HTTP 201.
- `GET /clientes?limit=20`: lista los clientes del tenant y devuelve `next_cursor` para paginación.
- `GET /clientes/{cliente_id}`: devuelve el cliente correspondiente o HTTP 404.
- Todas las rutas requieren `Authorization: Bearer TOKEN` de MS0 y rol ADMIN o COORDINADOR.

La empresa sale exclusivamente del contexto del autorizador MS0. No se admite un `tenant_id` arbitrario enviado por el navegador. La tabla exclusiva del servicio es `trazora-clientes-dev`, con PK `TENANT#<empresa>` y SK `CLIENTE#<id>`.

## Despliegue (EC2, AWS Academy)

```bash
cd ~/trazora-fsm
git pull --ff-only
export AWS_PROFILE=default
export AWS_REGION=us-east-1
export LAB_ROLE_ARN=$(aws iam get-role --role-name LabRole --query 'Role.Arn' --output text)
export MS0_AUTHORIZER_ARN=$(aws lambda get-function --function-name trazora-usuarios-dev-validarToken --query 'Configuration.FunctionArn' --output text --region us-east-1)
echo "$LAB_ROLE_ARN"
echo "$MS0_AUTHORIZER_ARN"
cd backend/clientes
serverless print --stage dev --region us-east-1
serverless deploy --stage dev --region us-east-1
serverless info --stage dev --region us-east-1
```

Verifica los ARN antes de desplegar. Si falla el permiso de invocación del autorizador externo, revisa CloudFormation y la política Lambda; no elimines la autorización ni conviertas la API en pública.

## Pruebas previstas

1. Sin token: listar clientes → 401.
2. ClimaLima ADMIN crea un cliente → 201; lo ve en su listado y detalle.
3. FríoSur ADMIN no lo ve en su listado.
4. FríoSur consulta el ID de ClimaLima → 404.
5. Enviar tenant_id en body de creación → 400.
6. Token vencido o revocado → 401.

Pendiente: actualizar clientes, ubicaciones, pruebas automáticas adicionales y carga masiva directa con Python/boto3 desde EC2.