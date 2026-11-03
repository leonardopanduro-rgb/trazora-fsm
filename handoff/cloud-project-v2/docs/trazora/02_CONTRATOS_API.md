# Contratos HTTP de Trazora FSM — APIs reales de desarrollo

**Fecha de corte:** 03/11/2026. **Fuente de verdad:** código backend en https://github.com/leonardopanduro-rgb/trazora-fsm. Las URL se tomaron de despliegues y pruebas reportados; si el laboratorio recrea API Gateway, hay que actualizarlas.

## 1. Entornos de las seis APIs

| Servicio | Variable Vite | Base URL dev |
|---|---|---|
| MS0 Autenticación | `VITE_API_MS0` | `https://3yti33bqaf.execute-api.us-east-1.amazonaws.com/dev` |
| MS1 Clientes | `VITE_API_MS1` | `https://9qksceoae2.execute-api.us-east-1.amazonaws.com/dev` |
| MS2 Técnicos | `VITE_API_MS2` | `https://lil6er5i20.execute-api.us-east-1.amazonaws.com/dev` |
| MS3 Órdenes | `VITE_API_MS3` | `https://ul25x5oe02.execute-api.us-east-1.amazonaws.com/dev` |
| MS4 Agenda | `VITE_API_MS4` | `https://4o2ucd2ati.execute-api.us-east-1.amazonaws.com/dev` |
| MS5 Partes | `VITE_API_MS5` | `https://v7hxmxlf03.execute-api.us-east-1.amazonaws.com/dev` |

Todas están en `us-east-1` con stage `dev`, son URLs públicas de enrutamiento (NO son credenciales). Exponer URLs en frontend es normal; proteger los datos depende del backend.

## 2. Autenticación MS0

**POST `/auth/login` — pública:** body exacto:

```json
{"tenant_id":"CLIMALIMA","email":"correo-de-prueba@example.com","password":"<contraseña-ingresada-por-el-usuario>"}
```

Respuesta HTTP 200 (campos relevantes):

```json
{
  "token": "<TOKEN_OPACO>",
  "token_type": "Bearer",
  "expires_at": "2026-11-03T17:00:00+00:00",
  "usuario": {
    "usuario_id": "<uuid>",
    "tenant_id": "CLIMALIMA",
    "email": "correo-de-prueba@example.com",
    "rol": "ADMIN"
  }
}
```

Es un ejemplo de estructura, **no un token real**. Cada login emite un token diferente, con expiración ~1 hora. Guardarlo inicialmente solo en memoria React. No guardar token/contraseña en localStorage, URL, logs ni Git.

- `GET /usuarios/me` — Bearer token, devuelve `usuario_id, tenant_id, email, rol, estado`.
- `POST /auth/logout` — Bearer token, respuesta `{"ok":true}`; invalida el token.
- `GET /health` — pública, solo diagnóstico.

Para MS1–MS5, enviar cabecera `Authorization: Bearer <token>`. **NO** enviar cabecera Authorization al subir directamente a S3 con un POST firmado.

## 3. MS1 Clientes

| Método | Ruta | Body | Respuesta |
|---|---|---|---|
| POST | `/clientes` | `{"nombre":"Comercial López","correo":"cliente@example.com","telefono":"999000111"}` | 201 `{"cliente": {cliente_id, tenant_id, nombre, correo, telefono, activo, creado_en}}` |
| GET | `/clientes?limit=20&cursor=...` | — | 200 `{"clientes":[...],"next_cursor":null|string}` |
| GET | `/clientes/{cliente_id}` | — | 200 `{"cliente":{...}}` o 404 |

No hay endpoints de edición ni de ubicaciones. No añadir `tenant_id` al POST: el backend lo rechaza con 400.

## 4. MS2 Técnicos y jornadas

| Método | Ruta | Body / notas |
|---|---|---|
| POST | `/tecnicos` | `{"nombre":"Carlos","especialidades":["REPARACION","MANTENIMIENTO"]}`. 201, devuelve `tecnico` con UUID |
| GET | `/tecnicos?limit=20&cursor=...` | 200 `{"tecnicos":[...],"next_cursor":null|string}` |
| GET | `/tecnicos/{tecnico_id}` | 200 técnico, 404 ajeno |
| PUT | `/tecnicos/{tecnico_id}/jornadas/{YYYY-MM-DD}` | `{"intervalos":[{"inicio":"09:00","fin":"12:00"}]}`; 200 devuelve `jornada` |
| GET | `/tecnicos/{tecnico_id}/jornadas?desde=YYYY-MM-DD&hasta=YYYY-MM-DD` | 200 `{"jornadas":[...]}`; rango máximo 31 días |

Especialidades aceptadas: `INSTALACION`, `MANTENIMIENTO`, `REPARACION`. Las horas de jornada usan bloques de 30 minutos, zona `America/Lima`.

## 5. MS3 Órdenes

| Método | Ruta | Body / respuesta |
|---|---|---|
| POST | `/ordenes` | `{"cliente_id":"<uuid-cliente-MS1>","tipo_servicio":"REPARACION","descripcion":"El aire acondicionado no enfría","prioridad":"ALTA"}`; 201 devuelve `{"orden":{orden_id,tenant_id,cliente_id,tipo_servicio,descripcion,prioridad,estado,...}}` |
| GET | `/ordenes?limit=20&cursor=...` | 200 `{"ordenes":[...],"next_cursor":null|string}` |
| GET | `/ordenes/{orden_id}` | 200 `{"orden":{...}}` o 404 |

El backend valida el cliente mediante **MS1 protegido** y crea la orden como `ABIERTA`. `tipo_servicio`: INSTALACION/MANTENIMIENTO/REPARACION. `prioridad`: BAJA/MEDIA/ALTA (por defecto MEDIA). No existe aún cambio de estado o cierre por API.

## 6. MS4 Agenda

| Método | Ruta | Body / respuesta |
|---|---|---|
| POST | `/visitas` | `{"orden_id":"<uuid>","tecnico_id":"<uuid>","inicio":"2026-11-17T15:00:00Z","fin":"2026-11-17T16:00:00Z"}`; 201 devuelve `{"visita":{...}}` |
| GET | `/visitas?limit=20&cursor=...` | 200 `{"visitas":[...],"next_cursor":null|string}` |
| GET | `/visitas/{visita_id}` | 200 `{"visita":{visita_id,orden_id,tecnico_id,inicio,fin,estado,...}}` o 404 |

La fecha del ejemplo es solo ilustrativa. El backend exige futuro, UTC con `Z`, inicio en minutos 00/30, duración 30–240 minutos y misma fecha en Lima. Verifica orden ABIERTA, técnico activo, especialidad compatible y jornada que cubre el intervalo. Si hay conflicto de bloque o jornada inválida devuelve **409**. La UI debe mostrar el error y solicitar otro horario. Todavía no hay endpoint de reprogramación/cancelación/inicio.

## 7. MS5 Partes y archivos S3

| Método | Ruta | Body / respuesta |
|---|---|---|
| POST | `/visitas/{visita_id}/partes` | body `{}`. Crea borrador 201; máximo uno por visita (409 si ya existe). |
| GET | `/visitas/{visita_id}/partes` | 200 `{"parte":{...}}` o 404 |
| GET | `/partes/{parte_id}` | 200 `{"parte":{...},"evidencias":[...]}` |
| PATCH | `/partes/{parte_id}` | `{"diagnostico":"...","tareas":["..."],"resultado":"RESUELTO","version":1}`. Sube versión, 200; versión antigua: 409 |
| POST | `/partes/{parte_id}/evidencias` | `{"content_type":"image/png"}`. Devuelve 201 con `evidencia` y `upload.url` + `upload.fields` |
| POST | `/partes/{parte_id}/evidencias/{evidencia_id}/confirmar` | body `{}`. Confirma objeto cargado, 200 |
| GET | `/partes/{parte_id}/evidencias/{evidencia_id}/descargar` | 200 devuelve URL de lectura temporal, solo si la evidencia está CONFIRMADA |

`resultado`: PENDIENTE, RESUELTO, REQUIERE_REVISITA, NO_ATENDIDO. **El parte permanece BORRADOR**, incluso si resultado=RESUELTO: no equivale a finalizar la visita. Archivo: PNG/JPEG de 1 a 5 MiB, bucket privado.

**Proceso de carga desde navegador:**
1. `POST /partes/{id}/evidencias` al backend con token y content_type.
2. Crear `FormData()`; agregar **todos** los pares recibidos en `upload.fields`, luego campo `file` con la imagen.
3. `fetch(upload.url,{method:"POST",body:formData})` sin cabecera Bearer ni establecer manualmente Content-Type multipart (el navegador genera el boundary). S3 suele responder 204.
4. `POST /partes/{id}/evidencias/{evidencia_id}/confirmar` con token para marcar CONFIRMADA.
5. Para ver la imagen: solicitar `.../descargar` con token, abrir la URL temporal devuelta. No almacenar ni compartir URLs S3 firmadas.

## 8. Errores, permisos y paginación

- `401`: sesión inválida/ausente/expirada. Borrar el token en memoria y mostrar login.
- `403`: rol sin permiso.
- `404`: recurso inexistente **o de otra empresa**. No distinguirlos públicamente.
- `409`: conflicto (bloque horario, versión de borrador, duplicado o estado).
- `400`: campos inválidos o intento de forzar `tenant_id`.
- `502`: algún servicio interno no respondió como se esperaba; mostrar mensaje recuperable.

Listas de MS1–MS4 usan `limit` (1–50, por defecto 20) y `next_cursor`; **no** asumir que el tamaño de una página es el total de registros. En el frontend ofrecer 'Cargar más' y enviar `cursor` con `encodeURIComponent`.

## 9. Rutas que NO existen hoy (no invocar)

- `GET/POST/PATCH /usuarios` para administrar cuentas.
- `/clientes/{id}/ubicaciones`.
- `/ordenes/{id}/cerrar`, `/cancelar`, `PATCH /ordenes/{id}`.
- `/visitas/{id}/iniciar`, `/reprogramar`, `/cancelar`, `/finalizar`.
- `/partes/{id}/finalizar`.
- `/disponibilidad`, `/analitica`, `/dashboard`.

Los diagramas de arquitectura del equipo contienen algunas de estas rutas como **diseño futuro**. Las pantallas deben reflejar el estado actual y desbloquearse cuando backend implemente y pruebe cada contrato.
