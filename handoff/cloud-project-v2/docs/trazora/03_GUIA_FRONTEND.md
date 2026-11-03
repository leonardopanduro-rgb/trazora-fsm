# Guía de implementación del frontend (React + Vite)

## Objetivo y límites

Construir una web SaaS con **la misma URL para todas las empresas**, pero contenido, menús y operaciones derivados de la sesión autenticada. Los tenants de demo son CLIMALIMA y FRIOSUR; TECNINORTE se cargará para evidencias de volumen.

La entrega inicial debe **consumir las APIs existentes**, no inventar endpoints. Ver `02_CONTRATOS_API.md`. Este paquete incluye un **starter React mínimo** con login y lectura de módulos; no es una aplicación final ni incluye lógica de finalización de visitas.

## Pantallas por orden de implementación

| Orden | Pantalla | Función hoy | Bloqueo/dependencia |
|---|---|---|---|
| 1 | Login | Selección de empresa, correo, contraseña; POST MS0, guardar token en memoria, GET perfil, logout | Activo |
| 2 | Panel / navegación | Mostrar empresa y rol, links a clientes, técnicos, órdenes, visitas y partes | No mostrar falsos conteos totales calculados con una sola página |
| 3 | Clientes | GET paginado, POST alta, GET detalle | MS1; ubicaciones aún no están |
| 4 | Técnicos | GET paginado, POST alta, GET detalle, PUT/GET jornadas | MS2; ausencias faltan |
| 5 | Órdenes | GET paginado, POST alta con cliente de MS1, GET detalle | MS3; cerrar/cancelar pendientes |
| 6 | Agenda | GET visitas, POST con orden/técnico y horario válido, GET detalle | MS4; iniciar/reprogramar/cancelar pendientes |
| 7 | Partes | GET/POST borrador por visita, GET/PATCH parte; foto PNG/JPG mediante POST firmado a S3 y confirmación | MS5; finalizar parte pendiente |
| 8 | Administración de usuarios / técnico móvil | Diseñar pantalla y dejar deshabilitada hasta tener APIs reales y validación de asignación | Trabajo backend pendiente |

No ocultar un fallo de API como si un guardado hubiese sido exitoso. Mostrar loading, éxito real, validaciones 400, falta de permisos 403, sesión expirada 401, 404 y conflicto 409.

## Plan de trabajo colaborativo sugerido

| Responsable a asignar | Rama | Entrega y criterio |
|---|---|---|
| Front A (base) | `feat/front-auth-shell` | Vite+React, variables Vite, API client único, login/perfil/logout, navegación, estado vacío y 401 |
| Front B | `feat/front-clientes-tecnicos` | Tablas/listas paginadas y formularios de clientes, técnicos, especialidades y jornadas |
| Front C | `feat/front-ordenes-agenda` | Orden con selección de cliente y agenda con técnico/fecha; manejo 409 por conflicto |
| Front D | `feat/front-partes-s3` | Borrador de parte, edición con version, carga S3 multipart y confirmación, preview por URL temporal |
| Integración/revisor | `feat/front-amplify-tests` | Revisar PR, verificar 2 tenants, UI adaptable a móvil, desplegar a Amplify y guardar evidencias |

Si el equipo tiene menos integrantes disponibles para frontend, combinar responsables; si tiene más, dividir por pantallas y pruebas. Ninguna persona debe modificar `main` de forma unilateral sin avisar. Crear PR pequeño por pantalla, probar con sesión de CLIMALIMA y FRIOSUR antes de mezclar.

## Arquitectura y seguridad frontend

- React con Vite/TypeScript, rutas protegidas y un módulo de API centralizado. Las bases de las seis APIs se configuran mediante `VITE_API_MS0` ... `VITE_API_MS5`.
- Variables Vite **no son secretas**; jamás incluir `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`, contraseñas o tokens en ellas.
- Token guardado **solo en memoria React** inicialmente. Al refrescar la pestaña, se inicia sesión de nuevo; es preferible a persistir tokens largos en almacenamiento web para esta versión académica.
- Nunca confiar en el `tenant_id` que se manda desde la UI para delimitar datos. Las APIs de negocio lo toman del token validado en MS0. Mostrar el tenant de `/usuarios/me`.
- En errores 401, borrar token en memoria y redirigir a login. En 403, ocultar o bloquear acción y mostrar falta de permiso. Repetir comprobación de backend siempre.
- Usar CORS de API Gateway y bucket S3 según origen de Amplify. No usar proxy de Vite para disfrazar errores CORS que aparecerán al publicar.
- Para S3, el backend devuelve **POST prefirmado**, no PUT; el navegador envía FormData y el archivo directo a S3. Ver sección MS5 de `02_CONTRATOS_API.md`.
- No almacenar URLs firmadas de S3 después de su vencimiento. Cuando el usuario vuelva a entrar, solicitar una nueva URL.
- Fechas de visita: UI en zona horaria `America/Lima`, backend exige UTC ISO `Z`. Intervalos de 30 minutos, duración hasta 4 horas. Confirmar jornada real de MS2 antes de presentar como disponible.
- Toda lista de MS1–MS4 es paginada; implementar "Cargar más" con `next_cursor` y mantener valores existentes.

## Flujo práctico desde el frontend

1. Elegir tenant, iniciar sesión, recibir token y perfil. Mostrar CLIMALIMA / ADMIN.
2. Buscar/crear cliente y copiar su `cliente_id`.
3. Crear orden de reparación con ese `cliente_id`.
4. Seleccionar técnico con especialidad REPARACION, verificar/crear jornada y programar visita.
5. Recuperar la visita y crear borrador de parte.
6. Actualizar diagnóstico y resultado; subir PNG/JPG directo a S3 con formulario firmado; confirmar y mostrar evidencia.
7. Mostrar "Borrador guardado". **No** mostrar "Visita finalizada / Orden cerrada" hasta que backend implemente esas transiciones.
8. Salir, entrar como FRIOSUR y comprobar que no ve clientes, órdenes, visitas ni partes de CLIMALIMA.

## Checklist antes de cada PR

- [ ] Sin credenciales ni token en commit, logs o screenshot.
- [ ] Manejo de estados loading, vacío, error y éxito real.
- [ ] IDs obtenidos del backend, no IDs inventados.
- [ ] Requests protegidas llevan Bearer token; S3 directo NO lleva Bearer token.
- [ ] Funciona con dos tenants y no muestra datos cruzados.
- [ ] Errores 401/403/404/409 representados de modo comprensible.
- [ ] Probado el build: `npm run build`.
- [ ] Pantallas de técnico, cierre y finalización aparecen deshabilitadas o con aviso si no tienen endpoint.
- [ ] PR describe pruebas manuales y evidencia (sin contraseñas).

## Desarrollo local y Amplify Hosting

Con el starter del paquete:

```bash
cd frontend
cp .env.example .env
npm install
npm run dev
```

Revisar URLs en `.env` si el laboratorio cambia recursos. Para publicar en Amplify:
1. Vincular el repositorio `rvcuba-utec/cloud-project-v2` y la rama integrada.
2. Configurar proyecto frontend dentro de carpeta `frontend` (monorepo, app root). Comando de build `npm run build`, directorio de salida `dist`. Si se usa npm ci, confirmar y subir `package-lock.json`.
3. Configurar las seis variables `VITE_API_MS*` en el entorno de Amplify. Son URLs públicas, no secretos.
4. Revisar que el dominio de Amplify pueda llamar a API Gateway y a S3 (CORS del bucket); restringir orígenes S3 al dominio definitivo antes de demo pública.
5. Probar login, listas, alta de cliente, visita y evidencia desde la URL publicada y móvil.
6. Guardar link Amplify, capturas y commit exacto para el informe.

**El proyecto exige automatización de infraestructura con Serverless Framework.** Crear la aplicación Amplify manualmente puede servir para la primera integración, pero documentar/automatizar el despliegue definitivo para la entrega final.
