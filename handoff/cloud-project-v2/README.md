# Traspaso de Trazora FSM al repositorio del equipo

**Destino:** https://github.com/rvcuba-utec/cloud-project-v2  
**Fuente de la implementación:** https://github.com/leonardopanduro-rgb/trazora-fsm

Este directorio existe para **entregar documentación, contratos de APIs y un starter React** sin tocar los diagramas, materiales o propuesta que ya están en el repositorio de colaboración.

## Contenido

- `docs/trazora/01_ESTADO_REAL.md` — qué está realmente implementado vs lo pendiente.
- `docs/trazora/02_CONTRATOS_API.md` — URLs MS0–MS5, operaciones, entradas, salidas y errores.
- `docs/trazora/03_GUIA_FRONTEND.md` — pantallas, arquitectura React, división de trabajo y Amplify.
- `docs/trazora/04_BACKEND_PENDIENTES.md` — trabajo de eventos, flujo FSM, volumen, seguridad y entrega.
- `docs/trazora/05_MENSAJE_EQUIPO.md` — mensaje listo para copiar al chat/grupo.
- `frontend/` — starter React + Vite + TypeScript, **no producto terminado**.

## Cómo pasar esto al repo del equipo sin sobrescribir sus documentos

La integración GitHub conectada al asistente **puede leer** `rvcuba-utec/cloud-project-v2`, pero al intentar crear una rama allí respondió `403 Resource not accessible by integration`. Por eso el traspaso se preparó en el repositorio de Trazora en lugar de afirmar que ya se escribió en el destino.

Un colaborador con permisos de escritura en `rvcuba-utec/cloud-project-v2` puede hacer:

```bash
git clone https://github.com/rvcuba-utec/cloud-project-v2.git
git clone https://github.com/leonardopanduro-rgb/trazora-fsm.git

cd cloud-project-v2
git switch -c feat/trazora-frontend-handoff

mkdir -p docs/trazora
cp -a ../trazora-fsm/handoff/cloud-project-v2/docs/trazora/. docs/trazora/
cp -a ../trazora-fsm/handoff/cloud-project-v2/frontend ./frontend

git add docs/trazora frontend
git commit -m "docs(frontend): integrate Trazora API contracts and React starter"
git push -u origin feat/trazora-frontend-handoff
```

Luego abrir un PR hacia `main` de `cloud-project-v2` y pedir revisión al equipo. Los comandos usan rutas relativas; hazlos desde un directorio donde los dos repositorios sean carpetas hermanas. Si el colaborador no tiene permisos de push, el propietario debe otorgarlos. **Antes de ejecutar cp, comprueba que frontend no exista o esté vacío**; si ya hay trabajo en otra rama, integrar archivos manualmente sin sobrescribirlo.

No copiar las carpetas `backend/` ni `infra/` al repositorio de frontend como si fueran otra implementación: el backend está versionado por separado y desplegado en AWS.

## Ejecutar starter React

```bash
cd cloud-project-v2/frontend
cp .env.example .env
npm install
npm run dev
```

El starter solo ofrece login y una base inicial de lectura; el equipo debe terminar formularios/estados/archivos y publicar en Amplify. Ver `frontend/README.md`. Nunca añadir secretos a `.env` ni subirlo a Git.

## Importante

Los seis IDs de API Gateway utilizados en `.env.example` eran válidos para el entorno académico al 03/11/2026, pero **pueden cambiar si se recrea el laboratorio**. Si una URL deja de funcionar, revisar el resultado real de `serverless info` y actualizar la variable correspondiente.
