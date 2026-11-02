# MS2 — Técnicos y jornadas (primer incremento)

**Estado:** código e infraestructura en GitHub. No significa que ya estén desplegados en tu cuenta de AWS.

Este microservicio es independiente de MS0 Usuarios y MS1 Clientes. No crea usuarios, no almacena contraseñas y no usa la tabla DynamoDB de MS0; consume únicamente su **autorizador Lambda** para obtener identidad, tenant y rol confiables.

## Operaciones incluidas

| Método | Ruta | Descripción |
|---|---|---|
| POST | `/tecnicos` | Registrar técnico del tenant autenticado |
| GET | `/tecnicos?limit=20` | Listar técnicos del tenant, con cursor |
| GET | `/tecnicos/{tecnico_id}` | Consultar un técnico |
| PUT | `/tecnicos/{tecnico_id}/jornadas/{fecha}` | Crear o reemplazar una jornada |
| GET | `/tecnicos/{tecnico_id}/jornadas?desde=YYYY-MM-DD&hasta=YYYY-MM-DD` | Listar jornadas hasta 31 días |

Todos los métodos requieren `Authorization: Bearer TOKEN` generado por MS0. Para este incremento se permite `ADMIN` o `COORDINADOR`; el acceso del `TECNICO` a su perfil y visitas se definirá cuando integremos MS2 con MS0/MS4.

### Datos aceptados

Ejemplo de creación de técnico:

```json
{
  "nombre": "Carlos de prueba",
  "especialidades": ["REPARACION", "MANTENIMIENTO"]
}
```

Especialidades permitidas: `INSTALACION`, `MANTENIMIENTO` y `REPARACION`. El backend genera automáticamente `tecnico_id`, `tenant_id`, `activo=true` y `creado_en`.

Ejemplo de jornada del 10 de noviembre de 2026:

```json
{
  "intervalos": [
    {"inicio": "08:00", "fin": "12:00"},
    {"inicio": "13:00", "fin": "17:00"}
  ]
}
```

El backend valida fechas ISO, horas en bloques de 30 minutos, intervalos ordenados y sin superposición. La zona horaria es `America/Lima`. El `PUT` reemplaza la jornada de esa fecha. No envíes `tenant_id` ni `tecnico_id` en los bodies: son datos de autoridad validados internamente.

### Diseño DynamoDB

Tabla por entorno: `trazora-tecnicos-dev`. Claves de tipo string:

- `PK = TENANT#CLIMALIMA`, `SK = TECNICO#<uuid>`
- `PK = TENANT#CLIMALIMA`, `SK = JORNADA#<uuid-tecnico>#2026-11-10`

Las consultas siempre utilizan `PK` construida a partir del token validado. Por tanto, conocer el ID de un técnico de otra empresa no permite consultarlo; se recibe HTTP 404.

## Despliegue en EC2 (AWS Academy)

```bash
cd ~/trazora-fsm
git pull --ff-only
export AWS_PROFILE=default
export AWS_REGION=us-east-1
export LAB_ROLE_ARN=$(aws iam get-role --role-name LabRole --query 'Role.Arn' --output text)
export MS0_AUTHORIZER_ARN=$(aws lambda get-function --function-name trazora-usuarios-dev-validarToken --query 'Configuration.FunctionArn' --output text --region us-east-1)
echo "$LAB_ROLE_ARN"
echo "$MS0_AUTHORIZER_ARN"

cd backend/tecnicos
python3 -m py_compile handler.py
serverless print --stage dev --region us-east-1
serverless deploy --stage dev --region us-east-1
serverless info --stage dev --region us-east-1
```

Si cualquiera de los dos ARN está vacío o corresponde a otro entorno, **no despliegues**. Un error de invocación del autorizador se resuelve revisando permisos de API Gateway/Lambda, no quitando autenticación.

## Pruebas

La prueba interactiva en `scripts/pruebas/probar_ms2.py` requiere la **URL real de la API MS2**, devuelta por `serverless info`. No pegues la URL de MS0 ni de MS1.

Desde la raíz:

```bash
python3 scripts/pruebas/probar_ms2.py
```

Verifica: 401 sin token, 201 al crear técnico ClimaLima, 200 al consultarlo, 404 al consultar ese ID con FríoSur, 200 al crear/consultar jornada, y 400 al intentar forzar `tenant_id` en el JSON. La prueba pide confirmación y crea un registro ficticio; no imprime tokens ni contraseñas.

## Límites pendientes de MS2

- La tabla no tiene aun ausencias, asociación verificada con `usuario_id` de MS0, modificación/desactivación de técnico, filtros por especialidad ni concurrencia para edición de jornadas.
- Reservar visitas, evitar solapamientos y verificar ausencias son responsabilidades de la integración posterior de MS4 Agenda.
- La carga de 30 000 registros por microservicio se realizará más adelante con Python/boto3 desde la EC2, no mediante esta API.
- `DeletionPolicy: Retain` deja la tabla si eliminas el stack. No uses `serverless remove` sin revisar datos y recursos.
