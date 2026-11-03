# MS5 — Partes de trabajo y evidencias (incremento inicial)

**Estado:** código preparado en GitHub; NO se ha desplegado automáticamente en AWS.

Esta primera versión se ajusta al estado actual de MS4: las visitas pueden estar `PROGRAMADA`, pero aún no existe en MS4 el endpoint `iniciar`. Por ello, MS5 permite crear y editar **borradores administrativos**, y cargar/confirmar evidencias, pero **NO finaliza partes ni actualiza automáticamente Órdenes**. Esa transición se implementará junto con inicio/finalización de visitas y eventos SNS/SQS.

## Endpoints protegidos por MS0

- `POST /visitas/{visita_id}/partes`: crea un borrador para una visita validada con la API MS4, solo uno por visita, HTTP 201.
- `GET /visitas/{visita_id}/partes`: recupera el parte existente o devuelve 404.
- `GET /partes/{parte_id}`: consulta el borrador y sus metadatos de evidencias.
- `PATCH /partes/{parte_id}`: actualiza diagnóstico, tareas y resultado mediante `version` para evitar sobrescrituras concurrentes.
- `POST /partes/{parte_id}/evidencias`: crea metadatos pendientes y entrega un **formulario S3 prefirmado** para imagen PNG/JPEG.
- `POST /partes/{parte_id}/evidencias/{evidencia_id}/confirmar`: comprueba el objeto real en S3 (tipo y tamaño) y marca evidencia `CONFIRMADA`.
- `GET /partes/{parte_id}/evidencias/{evidencia_id}/descargar`: devuelve una URL de lectura prefirmada, solo para evidencia confirmada.

Roles habilitados por ahora: ADMIN y COORDINADOR de su tenant. MS0 valida y obtiene `usuario_id`, `tenant_id` y `rol`. No admite la empresa indicada en JSON como autoridad.

## Ejemplos

Crear borrador de una visita existente:

```http
POST /dev/visitas/<visita_id>/partes
Authorization: Bearer <token_MS0>
Content-Type: application/json

{}
```

Editar borrador:

```json
{
  "diagnostico": "Filtro de aire obstruido",
  "tareas": ["Limpiar filtro", "Comprobar enfriamiento"],
  "resultado": "RESUELTO",
  "version": 1
}
```

El estado del parte sigue siendo `BORRADOR`, aunque el resultado sea `RESUELTO`, hasta implementar finalización real. El número de versión sube al actualizar: reenviar una versión antigua devuelve 409.

Pedir carga de imagen:

```json
{"content_type": "image/png"}
```

La respuesta contiene `upload.url` y `upload.fields`, que son valores **temporales y sensibles** para subir el objeto a S3 mediante `multipart/form-data`. No los compartas ni guardes en GitHub o capturas. Solo después de subir el archivo se puede confirmar. Tamaño permitido: 1–5 MiB, tipo PNG o JPEG. Para consultar evidencias, siempre se verifica primero el tenant del token.

## Diseño de datos

Tabla exclusiva `trazora-partes-dev`:

- PK `TENANT#CLIMALIMA` + SK `PARTE#uuid`.
- PK `TENANT#CLIMALIMA` + SK `VISITA_PARTE#uuid_visita` para garantizar un parte por visita (transacción).
- PK `TENANT#CLIMALIMA` + SK `EVIDENCIA#uuid_parte#uuid_evidencia`.

Bucket S3 privado `trazora-fsm-evidencias-<accountId>-dev-us-east-1`, construido por Serverless con Bloqueo de acceso público y SSE-S3. Para el entorno dev, la regla CORS de S3 permite orígenes `*` **solo para que funcionen futuras pruebas desde navegador**; antes de publicar React hay que restringirla al origen autorizado de Amplify.

Usamos el `LabRole` existente, porque AWS Academy podría no permitir crear roles nuevos. Si Lambda falla con AccessDenied en `s3:PutObject`, `s3:GetObject`, `dynamodb:TransactWriteItems` o `dynamodb:UpdateItem`, no cambies a un rol administrador permanente ni abras el bucket: revisaremos las restricciones del laboratorio.

## Despliegue desde EC2

```bash
cd ~/trazora-fsm
git status
git pull --ff-only

export AWS_PROFILE=default
export AWS_REGION=us-east-1
export LAB_ROLE_ARN=$(aws iam get-role --role-name LabRole --query 'Role.Arn' --output text)
export MS0_AUTHORIZER_ARN=$(aws lambda get-function --function-name trazora-usuarios-dev-validarToken --query 'Configuration.FunctionArn' --output text --region us-east-1)
export MS4_AGENDA_API_BASE=https://4o2ucd2ati.execute-api.us-east-1.amazonaws.com/dev

cd backend/partes
python3 -m py_compile handler.py
serverless print --stage dev --region us-east-1
serverless deploy --stage dev --region us-east-1
serverless info --stage dev --region us-east-1
```

Confirma que los ARN son reales y que las credenciales AWS Academy aún están vigentes. No uses un marcador de URL ni agregues `/visitas` al final de `MS4_AGENDA_API_BASE`.

Al terminar deberías ver `trazora-partes-dev` en DynamoDB y un bucket S3 con acceso público bloqueado.

## Prueba de integración

```bash
cd ~/trazora-fsm
python3 scripts/pruebas/probar_ms5.py
```

El programa solicita el endpoint real de MS5, autentica ambas empresas, localiza una visita PROGRAMADA de ClimaLima, pide aprobación para crear un borrador y comprueba: consulta propia, versión de actualización, 404 de FríoSur sobre parte ajeno, rechazo de tenant forzado, evidencia en S3 con confirmación. La prueba **genera una imagen PNG ficticia de 1 píxel** y la carga solo cuando confirmas; no sube fotos personales ni muestra tokens o URLs firmadas.

El bucket y la tabla usan `DeletionPolicy: Retain`. No ejecutes `serverless remove` para corregir errores sin revisar los recursos retenidos. El almacenamiento de S3 y DynamoDB puede consumir cuota o créditos del laboratorio.

## Pendiente para finalizar el proyecto académico

- MS4 iniciar/finalizar visitas y validar técnico asignado, no solo administradores.
- MS5 finalizar partes, impedir duplicados, generar evento OUTBOX y conectar SNS/SQS con MS4/MS3.
- Evidencias con metadatos y permisos más detallados, auditoría y restricciones CORS por dominio.
- Carga directa de 30 000 registros por microservicio desde EC2 con Python/boto3, sin usar las APIs REST.
- React en Amplify conectado a los endpoints protegidos.
