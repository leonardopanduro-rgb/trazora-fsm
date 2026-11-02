# MS0 — Primer login multitenant (desarrollo)

## Estado
Código preparado en GitHub. No se despliega en tu cuenta automáticamente. Debes ejecutar Serverless desde EC2 con tus credenciales temporales.

## Endpoints
- GET /dev/health: público, verificación
- POST /dev/auth/login: público, recibe tenant_id, email y password
- GET /dev/usuarios/me: protegido con Authorization: Bearer TOKEN
- POST /dev/auth/logout: protegido, revoca el token

Body de login (valores ilustrativos):
```json
{"tenant_id":"CLIMALIMA","email":"admin-clima@example.com","password":"TU_CONTRASEÑA_REAL"}
```
No guardes contraseñas o tokens en capturas, git ni registros. Inicia sesión con Postman o un cliente seguro.

## Despliegue
En EC2:
```bash
cd ~/trazora-fsm
git pull --ff-only
export AWS_PROFILE=default
export AWS_REGION=us-east-1
export LAB_ROLE_ARN=$(aws iam get-role --role-name LabRole --query 'Role.Arn' --output text)
cd backend/usuarios
serverless print --stage dev --region us-east-1
serverless deploy --stage dev --region us-east-1
serverless info --stage dev --region us-east-1
```
Si no tienes permiso iam:GetRole, configura LAB_ROLE_ARN manualmente usando el ARN previamente confirmado. No ejecutes deploy con rol inválido.

## Crear administradores de prueba de forma segura
Desde la raíz del repositorio de EC2 (una vez desplegadas las tablas):
```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r scripts/bootstrap/requirements.txt
python scripts/bootstrap/crear_admin.py --tenant CLIMALIMA --email admin-clima@example.com
python scripts/bootstrap/crear_admin.py --tenant FRIOSUR --email admin-frio@example.com
```
Sustituye los correos de ejemplo por los reales de las cuentas de prueba (no es necesario que sean personales). El script solicita la contraseña con entrada oculta y guarda solo su hash. Una transacción crea usuario, marcador de email y bloqueo de bootstrap. No permite ejecutar el bootstrap dos veces para el mismo tenant. No existe API pública de registro ni se pueden elegir roles por HTTP.

## Pruebas en Postman
1. Login de CLIMALIMA: debe devolver 200, token y perfil de CLIMALIMA.
2. GET /usuarios/me con Bearer token de CLIMALIMA: debe mostrar CLIMALIMA.
3. Login de FRIOSUR: debe devolver token y perfil independientes.
4. Login con contraseña incorrecta: 401.
5. GET /usuarios/me sin Authorization: 401.
6. POST /auth/logout con token de CLIMALIMA: 200, y luego /usuarios/me con el mismo token: 401.

No pruebas todavía acceso cruzado a Clientes u Órdenes, porque esos servicios no están implementados.

## Precauciones y tareas pendientes
- El autorizador obtiene tenant y rol desde DynamoDB; no se autoriza por un tenant_id arbitrario del navegador.
- PBKDF2-SHA256 con sal aleatoria y 600 000 iteraciones evita contraseñas en texto plano; valorar Argon2id con paquete/layer y pruebas de empaquetado antes de producción.
- Token aleatorio de alta entropía, hash SHA256 almacenado en tabla, duración una hora y revocación remota.
- Deshabilitada la caché del autorizador; verifica expiración por código porque DynamoDB TTL elimina de forma diferida.
- Falta rate limiting específico de login, controles de abuso, administración por roles, auditoría, respuesta CORS de errores 4XX y configuración de origen de frontend antes de producción.
- La cuenta AWS Academy puede limitar permisos de Lambda sobre DynamoDB o de API Gateway; inspecciona CloudWatch si hay HTTP 500 y nunca muestres claves.
- Solo se han preparado endpoints MS0, no se garantiza todavía despliegue o funcionamiento real en tu cuenta.
