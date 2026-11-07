# MS2 estado del técnico y validación de reservas — primera ampliación

**Rama:** `feature/ms2-estado-tecnicos-2026-11-04` (basada en `integracion/backend-datos-renzo-2026-11-04`). **No desplegado aún al crear este documento.**

## Nuevas rutas protegidas

| Servicio | Método/ruta | Rol | Qué hace |
|---|---|---|---|
| MS2 Técnicos | `PATCH /tecnicos/{tecnico_id}/estado` | Solo ADMIN | Con `{"activo":false}` desactiva; `{"activo":true}` reactiva. HTTP 200 devuelve `{"tecnico":{...},"sin_cambios":boolean}`. |
| MS4 Agenda | `GET /tecnicos/{tecnico_id}/reservas-futuras` | ADMIN/COORDINADOR | Devuelve `{"tecnico_id":"...","tiene_reservas":true|false}` para el tenant del token. |

**Validaciones:** 401 sin sesión, 403 si no es ADMIN para modificar estado, 404 si el técnico no es de la empresa, 400 si `activo` no es estrictamente booleano o se intenta enviar `tenant_id`, 409 si hay reservas activas, 503 si Agenda no puede verificar las reservas. El cambio en DynamoDB usa una escritura condicional para rechazar actualizaciones concurrentes del mismo estado.

La comprobación de MS4 usa una consulta **por clave de partición y sort key**, no `Scan`: `PK=TENANT#...` y `SK=BLOQUE#<tecnico_id>#<ISO_UTC>`. Cada visita programada genera bloques de 30 minutos. Busca desde el bloque de la media hora actual hacia el futuro; por lo tanto detecta reservas en curso/futuras. Para cancelar o reprogramar en el futuro, MS4 deberá liberar/reemplazar bloques de manera atómica.

**Limitación de concurrencia:** MS2 y MS4 tienen dos tablas independientes. La comprobación por API y la actualización del técnico **no son una única transacción entre servicios**. Ante programación simultánea y desactivación todavía existe una carrera; al desarrollar el ciclo completo de MS4 se implementará una coordinación adicional o una reserva basada en estado con garantías transaccionales. Hasta entonces no debe afirmarse que el bloqueo sea infalible bajo concurrencia extrema.

## Orden correcto de despliegue en EC2

1. Actualiza las credenciales AWS Academy si vencieron y comprueba `aws sts get-caller-identity`.
2. Haz `git fetch origin`, cambia a la rama de feature, conserva el entorno `.venv`.
3. Configura variables (URLs conocidas de las APIs, sin credenciales en Git):

```bash
export AWS_PROFILE=default
export AWS_REGION=us-east-1
export LAB_ROLE_ARN=$(aws iam get-role --role-name LabRole --query 'Role.Arn' --output text)
export MS0_AUTHORIZER_ARN=$(aws lambda get-function --function-name trazora-usuarios-dev-validarToken --query 'Configuration.FunctionArn' --output text --region us-east-1)
export MS3_ORDENES_API_BASE=https://ul25x5oe02.execute-api.us-east-1.amazonaws.com/dev
export MS2_TECNICOS_API_BASE=https://lil6er5i20.execute-api.us-east-1.amazonaws.com/dev
export MS4_AGENDA_API_BASE=https://4o2ucd2ati.execute-api.us-east-1.amazonaws.com/dev
```

4. Verifica la sintaxis local: `python3 -m py_compile backend/tecnicos/handler.py backend/agenda/handler.py scripts/pruebas/probar_ms2_estado.py`. Ejecuta pruebas unitarias: `python3 -m unittest discover -s tests -p 'test_ms2_estado.py' -v`.
5. **Despliega primero MS4 Agenda** porque MS2 necesita su nueva ruta para verificar las reservas:

```bash
cd ~/trazora-fsm/backend/agenda
serverless print --stage dev --region us-east-1
serverless deploy --stage dev --region us-east-1
```

6. **Despliega MS2 Técnicos**:

```bash
cd ~/trazora-fsm/backend/tecnicos
serverless print --stage dev --region us-east-1
serverless deploy --stage dev --region us-east-1
```

7. Ejecuta prueba interactiva (crea un técnico nuevo solo con `SI`; no modifica los anteriores):

```bash
cd ~/trazora-fsm
python3 scripts/pruebas/probar_ms2_estado.py
```

URL MS2 a pegar: `https://lil6er5i20.execute-api.us-east-1.amazonaws.com/dev` (verifica con `serverless info` si cambia). Se requieren contraseñas de admins CLIMALIMA/FRIOSUR, pero el script no las imprime.

## Pendientes siguientes

- Crear pruebas de desactivación con una visita programada de MS4, comprobar 409 y no modificar reservas existentes.
- Resolver carrera potencial entre reservar una visita y desactivar un técnico dentro del siguiente incremento MS4.
- Editar perfiles, ausencias, identidad del técnico con MS0 y mejores validaciones de cambio de jornada.
- Cerrar flujo MS3/MS4/MS5 y luego integrar SNS/SQS; **no** desplegar el stack de eventos como parte de esta ampliación.
