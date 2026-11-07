# TRAZORA / Field Operations

**Frontend React diseñado específicamente para Trazora FSM (Grupo 5, Cloud Computing 2026-2).** Interfaz responsive para operaciones de campo: panel ejecutivo, clientes, técnicos, órdenes, agenda, partes con carga privada en S3 y trazabilidad de eventos.

> Este ZIP contiene **código fuente completo** y un **modo demo interactivo**, no credenciales ni datos reales. Las funciones reales requieren las seis APIs de AWS Academy disponibles. No se necesita Codex para ejecutar o modificar el proyecto.

## Iniciar localmente

Requisitos: Node.js 20.19+ o 22+, npm.

```bash
npm install
cp .env.example .env
npm run dev
```

Abrir la URL local que muestra Vite (generalmente `http://localhost:5173`). Para compilar:

```bash
npm run build
npm run preview
```

`dist/` es la carpeta que se publica en Amplify. Usa `npm install` la primera vez para generar `package-lock.json`. No subas `.env` al repositorio.

## Primer recorrido

1. En el login, pulsa **Explorar demo interactiva** sin cuenta para ver todas las pantallas. Los datos son ficticios y cualquier creación demo se queda únicamente en memoria del navegador.
2. Para datos reales, selecciona empresa y entra con correo y contraseña de **MS0**. Las claves nunca van al código ni al repositorio; el token se conserva **solo en memoria React** y al recargar se requiere login nuevamente.
3. Visita `Vista general`, `Órdenes`, `Agenda`, `Clientes`, `Equipo técnico`, `Partes y evidencias`, `Trazabilidad` y `Configuración`. El panel calcula cantidades **solo sobre la página cargada** (no 30 000 registros ni conteos globales).
4. Crea cliente / técnico / orden / visita desde los formularios. Agenda valida en el backend jornadas y reservas; el frontend respeta la respuesta 409.
5. En Partes, selecciona o pega el UUID de una visita. Crear o recuperar borrador → editar → cargar imagen PNG/JPG mediante el **POST prefirmado S3** → confirmar → finalizar. El botón de finalización se activa con resultado válido y al menos una evidencia confirmada (en modo real).
6. Observa estado `PENDIENTE_PUBLICACION` o `PUBLICADO` en la confirmación; después actualiza Agenda/Órdenes. Los eventos se propagan por SNS y SQS de forma asincrónica.

## Contratos reales (sin inventar endpoints)

Las bases de API Gateway se leen desde `VITE_API_MS0` … `VITE_API_MS5` del archivo `.env`. `.env.example` tiene las URL del laboratorio documentadas previamente, **no garantizadas** si se recrea AWS Academy. Revísalas antes de demo.

- MS0: `/auth/login`, `/usuarios/me`, `/auth/logout`.
- MS1: `GET/POST /clientes`.
- MS2: `GET/POST /tecnicos` (detalle y jornada gestionada por backend, interfaz de creación de técnico en este paquete).
- MS3: `GET/POST /ordenes` y `GET /ordenes/{id}/historial` (ruta declarada en GitHub; verificar que esté desplegada, de lo contrario aparecerá un estado informativo en el detalle).
- MS4: `GET/POST /visitas`, `POST /visitas/{id}/iniciar` (declarada en backend).
- MS5: `GET/POST /visitas/{id}/partes`, `GET/PATCH /partes/{id}`, solicitud/confirmación de evidencia mediante S3 y `POST /partes/{id}/finalizar`.

**No existen aún** operaciones de cierre confirmado de una orden ni panel de administración de usuarios por API; se muestran estados para revisión, sin botones falsos. Tampoco está conectado el rol TÉCNICO asignado para finalizar partes: la integración actual de MS5 permite ADMIN y COORDINADOR.

## Publicar en AWS Amplify

Si el repositorio contiene este proyecto como carpeta `frontend/`, en **Amplify Hosting** crea una aplicación conectada al repositorio y configura **App root: `frontend`**. Comandos: `npm install` y `npm run build`; salida `dist`. En el panel de variables de entorno incorpora las **seis** `VITE_API_MS*` con URL actualizadas. No son credenciales. Para SPA configurar rewrite `/<*>` → `/index.html` (200), si utilizas rutas de navegador (esta versión usa navegación cliente sin paths separados).

El archivo `amplify.yml` de esta carpeta sirve para repositorio frontend independiente. Para el monorepo, utiliza `amplify-monorepo.yml` de este paquete y guárdalo como `amplify.yml` **en la raíz del repositorio**.

La carga a S3 exige CORS correcto en bucket para el origen real de Amplify. Jamás uses `VITE_` para keys AWS, contraseñas o tokens.

## Handoff al repositorio del equipo

Destino conocido: `https://github.com/rvcuba-utec/cloud-project-v2`.

Puedes copiar el contenido de este ZIP a la carpeta `frontend/` de una **rama nueva** en ese repositorio, revisar cambios de la carpeta antes de sobrescribir, ejecutar `npm run build` y abrir un PR. No reemplaces el backend ni `docs/` del equipo. El backend y eventos quedan versionados en `https://github.com/leonardopanduro-rgb/trazora-fsm`.

El usuario del laboratorio `voclabs` ha mostrado restricciones explícitas de IAM para DynamoDB desde EC2; **la web usa APIs protegidas**, nunca consulta DynamoDB con claves AWS. Las tareas de carga masiva y recuperación no forman parte del navegador.

## Aclaración de calidad

- **Visual:** sistema de diseño propio (forest green, arena, lima; tipografía Manrope/DM Sans; tarjetas operativas, agenda, estados, drawer y comando `Ctrl/Cmd+K`). No es una plantilla generada genérica.
- **Funcional:** las altas y cambios en modo real dependen de un HTTP 2xx de AWS. Si hay error, no simulamos un guardado exitoso.
- **Seguridad:** no hay tokens en localStorage, query string ni Git. Tenant proviene del autorizer y del token validado, nunca de formularios de negocio.
- **Limitaciones:** la UI se implementa según los contratos actuales; la verificación end-to-end, el dominio de Amplify, permisos de LabRole y configuración CORS finales siguen requiriendo pruebas reales.
