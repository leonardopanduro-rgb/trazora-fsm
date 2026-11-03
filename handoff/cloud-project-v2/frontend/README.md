# Frontend starter — Trazora FSM

Este es un **punto de partida React/Vite/TypeScript**, no un producto terminado. Tiene login MS0, logout, consulta de perfil, navegación, lectura paginada de MS1–MS4 y alta básica de Clientes. Las demás pantallas quedan identificadas como trabajo para el equipo.

## Ejecutar

```bash
cd frontend
cp .env.example .env
npm install
npm run dev
```

Abre la URL local de Vite. Usa cuentas de prueba propias de CLIMALIMA/FRIOSUR; no guardes credenciales ni tokens en Git. El token se conserva en **memoria**, por lo que recargar la página requiere iniciar sesión de nuevo.

Comprobar compilación:

```bash
npm run build
```

Para Amplify Hosting: conectar el repositorio del equipo, indicar raíz de aplicación `frontend`, compilar con `npm run build` y publicar `frontend/dist` (o `dist` respecto de appRoot). Configurar todas las variables `VITE_API_MS0`–`VITE_API_MS5`. No son secretos; **no** poner claves AWS allí. Generar y confirmar `package-lock.json` con `npm install` para usar `npm ci` en CI.

## Qué probar y construir

- Funciona: login/perfil/logout, error de contraseña y de sesión vencida, consulta de listas y crear cliente.
- Pendiente: formularios completos de técnicos/jornadas, órdenes, visitas y partes; evidencia S3 POST prefirmado; estados y UX móvil.
- **No existen hoy** backend de cerrar orden, iniciar/reprogramar/cancelar visita o finalizar parte; no habilitar esos botones como funcionales.
- Leer `docs/trazora/02_CONTRATOS_API.md` y `03_GUIA_FRONTEND.md` antes de implementar rutas.
- Todas las llamadas a APIs de negocio usan token validado; el S3 POST firmado nunca recibe el Bearer.
- Si aparece CORS desde Amplify, comprobar origen permitido en API Gateway y reglas del bucket S3; no desactivar la protección de la API.

La documentación original del equipo contiene ideas de un séptimo servicio (Analítica), que es **propuesto** y no está desplegado. Este starter apunta a las seis APIs reales MS0–MS5.
