# MS0 — Diseño inicial de tablas (etapa dev)

**Estado:** infraestructura declarada solamente. No se ha implementado login, bootstrap de administradores, validación de tokens ni autorización.

Este diseño usa una base DynamoDB exclusiva de MS0 y una tabla para sesiones. Los otros cinco microservicios tendrán sus propias tablas, no compartirán acceso directo a las tablas de MS0.

## Usuarios — `trazora-usuarios-dev`

Claves `PK` (partition key) y `SK` (sort key), ambas de tipo cadena.

Ejemplo de usuario:
```json
{
  "PK": "TENANT#CLIMALIMA",
  "SK": "USUARIO#USR-001",
  "entity_type": "USUARIO",
  "tenant_id": "CLIMALIMA",
  "usuario_id": "USR-001",
  "email_normalizado": "admin@example.com",
  "rol": "ADMIN",
  "estado": "ACTIVO",
  "password_hash": "<HASH_DERIVADO_EN_BACKEND>"
}
```

Ejemplo de marcador único de login **sin contraseña**:
```json
{
  "PK": "TENANT#CLIMALIMA",
  "SK": "LOGIN#admin@example.com",
  "entity_type": "LOGIN",
  "usuario_id": "USR-001"
}
```

El flujo de alta de usuario debe guardar **ambos registros mediante una transacción de DynamoDB con condiciones de no existencia**. Esto impide que se registre el mismo correo dos veces dentro de una empresa. Una consulta de login obtiene el marcador `LOGIN#email`, resuelve el usuario y solo entonces verifica la contraseña. No habilitar un registro público que pueda crearse cuentas ADMIN.

Para listar los usuarios del tenant se puede consultar la partición `TENANT#CLIMALIMA` filtrando por prefijo `USUARIO#` en SK, con paginación. El tenant real debe provenir de un contexto de autenticación validado, no de un valor arbitrario de la solicitud.

## Sesiones — `trazora-sesiones-dev`

Clave de partición `token_hash`. No guardar tokens de sesión en texto plano. Ejemplo:

```json
{
  "token_hash": "<SHA256_DEL_TOKEN_ALEATORIO>",
  "tenant_id": "CLIMALIMA",
  "usuario_id": "USR-001",
  "expires_at": 1794000000,
  "revocada": false
}
```

`expires_at` es un entero de segundos Unix UTC y es atributo TTL. **TTL no expira la autorización de inmediato**: la Lambda autorizadora debe validar explícitamente el vencimiento, la revocación, el estado del usuario y el tenant en cada solicitud (o diseñar cuidadosamente su política de caché).

## Próximo trabajo para que MS0 funcione
1. Código de inicio de sesión con validación tenant/email y verificación de hash de contraseña (p.ej. Argon2id).
2. Inicialización restringida del primer ADMIN de cada empresa.
3. Creación de token aleatorio seguro y registro de su hash en la tabla de sesiones.
4. Lambda autorizadora y endpoints protegidos.
5. Pruebas de aislamiento CLIMALIMA ↔ FRIOSUR, token vencido y roles.

Las dos tablas llevan `DeletionPolicy: Retain`: si se elimina el stack, **las tablas y sus datos permanecerán en la cuenta** y habrá que administrarlas explícitamente; no ejecutar `serverless remove` sin revisar las consecuencias. No ejecutar cargas masivas hasta tener acordado el contrato de datos y permisos.
