# Entrega del frontend — ZIP React y traspaso al repositorio del equipo

**Fecha:** 7 de noviembre de 2026. **Código principal/backend:** [trazora-fsm/main](https://github.com/leonardopanduro-rgb/trazora-fsm/tree/main). **Repositorio del equipo:** [rvcuba-utec/cloud-project-v2](https://github.com/rvcuba-utec/cloud-project-v2).

Se preparó una nueva aplicación React + Vite (ZIP completo entregado en la conversación de ChatGPT). **Este documento no afirma que el nuevo ZIP esté ya subido o descomprimido en GitHub.** El directorio `handoff/cloud-project-v2/frontend/` conserva el starter histórico previo. Para evitar perder el trabajo de la otra repo, integrar el nuevo ZIP mediante PR, no copiando a ciegas sobre `main`.

## Contenido del ZIP de frontend

Proyecto `trazora-frontend/` con `package.json`, `src/App.jsx`, `src/api.js`, `src/demo.js`, `src/styles.css`, `src/main.jsx`, `index.html`, `public/trazora-mark.svg`, `.env.example`, `amplify.yml`, `amplify-monorepo.yml` y `README.md`.

Incluye navegación, panel, clientes, técnicos, órdenes, agenda, formularios, partes/evidencias S3, trazabilidad de estados, login multitenant MS0 y demo ficticia explícita. Los formularios en modo real consumen los endpoints que existen; faltan algunas operaciones del backend (como cierre definitivo de orden y administración de usuarios).

## Instalar en el repositorio de colaboración

1. Descargar el ZIP desde ChatGPT y extraerlo localmente.
2. Clonar `cloud-project-v2`, crear rama `feat/trazora-front-premium` y **revisar** si ya existe una carpeta `frontend` con trabajo del equipo. Si existe, comparar cambios y conservar lo avanzado; no sobrescribir sin revisión.
3. Copiar los archivos de `trazora-frontend/` al directorio `frontend/` de la rama de colaboración.
4. Copiar `frontend/amplify-monorepo.yml` a `amplify.yml` **en la raíz del repositorio** si Amplify despliega ese monorepo.
5. Ejecutar `cd frontend && npm install && npm run build`. Confirmar `package-lock.json`; el ZIP fuente no incluye `node_modules` ni `dist`.
6. Crear `frontend/.env` a partir de `frontend/.env.example` con las URLs reales del laboratorio. No subir el archivo .env ni credenciales.
7. Realizar PR; probar login y un flujo de prueba con CLIMALIMA y FRIOSUR; conectar Amplify Hosting a la rama aprobada.

## Despliegue backend y eventos

No copiar `backend/` e `infra/` al repositorio de frontend para desplegarlos de nuevo accidentalmente. La implementación reside en Trazora, y la documentación actualizada de la prueba de eventos está en [ESTADO_INTEGRACION_2026-11-07.md](ESTADO_INTEGRACION_2026-11-07.md). Las Lambdas consumidoras manuales y SNS/SQS actuales pueden entrar en conflicto con stack nuevo; coordinar IaC antes de redeploy.

## Nota de verificación

La sintaxis JSX/JS del nuevo proyecto y CSS se verificó localmente antes de empaquetarlo. No se completó `npm run build` en el entorno de generación porque las dependencias npm no estaban instaladas allí; ese comando es obligatorio en la máquina de desarrollo o CI del equipo antes de presentar el frontend como listo para producción.
