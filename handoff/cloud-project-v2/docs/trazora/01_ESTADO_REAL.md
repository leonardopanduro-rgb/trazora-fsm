# Trazora FSM — Estado real y pendientes (03/11/2026)

> **Lectura obligatoria antes de desarrollar frontend.** Esta es una fotografía del código y de las pruebas realizadas en el entorno `dev`. **No confundir la propuesta/diagramas futuros de este repositorio con endpoints ya desplegados.**

## 1. Fuentes y repositorios

- **Backend y configuración realmente implementados:** https://github.com/leonardopanduro-rgb/trazora-fsm
- **Repositorio de colaboración y frontend del equipo:** https://github.com/rvcuba-utec/cloud-project-v2
- **Arquitectura objetivo del equipo:** `ideas/proposal.md`, `ideas/aws-architecture.md` y `diagrams/` del segundo repositorio.
- Esta entrega es un **handoff**: la documentación y el starter React pueden copiarse al repositorio del equipo; **NO** incluye credenciales temporales del laboratorio ni tokens de sesión.

## 2. Qué está implementado y probado

| Servicio | Operaciones que existen hoy | Evidencia reportada por quien desplegó | Qué NO está implementado |
|---|---|---|---|
| **MS0 Usuarios** | `POST /auth/login`, `GET /usuarios/me`, `POST /auth/logout`, `GET /health` y Lambda authorizer | Logins y perfil CLIMALIMA/FRIOSUR, revocación de token, rechazo de login cruzado | CRUD de usuarios, onboarding de técnicos, recuperación de contraseña para usuarios finales |
| **MS1 Clientes** | Crear, listar, buscar cliente | Prueba integrada de aislamiento y creación, HTTP 201/200/404 | Ubicaciones, editar/desactivar, búsqueda avanzada |
| **MS2 Técnicos** | Crear, listar, buscar técnico; guardar y listar jornadas | Aislamiento, jornada y validaciones probadas | Ausencias, editar/desactivar, vínculo con cuenta técnico |
| **MS3 Órdenes** | Crear/listar/buscar orden; validación del cliente por API de MS1 | Creación y aislamiento probados | Actualizar, cancelar, cerrar, historial de eventos y estados derivados |
| **MS4 Agenda** | Programar/listar/buscar visita; reservar bloques atómicos | Programación, 409 por duplicación, aislamiento probados | Inicio, reprogramación, cancelación, finalización y liberación de bloques |
| **MS5 Partes** | Crear/recuperar borrador, consultar/editar, solicitar carga S3, confirmar y leer evidencia privada | Prueba de borrador, evidencia S3, control de versión y aislamiento completada | Finalizar parte, publicar evento, vincular técnico asignado y actualizar visita/orden |

**Estado de la mensajería:** en el backend existe `infra/eventos/serverless.yml` para SNS, dos colas SQS y sus DLQ, pero en esta conversación **no se ha confirmado que ese stack esté desplegado**. Tampoco existen aún los publicadores/consumidores transaccionales. No dar por completada la arquitectura basada en eventos.

**Persistencia:** cada servicio tiene su tabla DynamoDB (MS0 cuenta con usuarios y sesiones); evidencias en bucket S3 privado de MS5. AWS Academy usa credenciales temporales y algunos recursos pueden cambiar si se restablece el laboratorio.

## 3. Discrepancia con la arquitectura objetivo

La documentación anterior del repositorio del equipo menciona **MS6 Analítica y siete microservicios**. La implementación efectiva tiene **seis: MS0 a MS5**. MS6 es una **ampliación planeada, no desplegada**. Por ahora, desarrollar contra las seis APIs reales. Si el equipo mantiene la idea de Analítica, debe asignarle responsable, datos, endpoints, despliegue y pruebas sin sacrificar los requisitos base.

La propuesta también menciona rutas como `/ordenes/{id}/cerrar`, `/visitas/{id}/iniciar` y `/partes/{id}/finalizar`: **todavía no existen**. Las pantallas deben mostrarlas como pendientes o usar datos simulados claramente etiquetados; nunca declarar al usuario que una orden quedó cerrada cuando el backend no lo hizo.

## 4. Prioridades verificables

| Urgencia | Entrega | Criterio de aceptación |
|---|---|---|
| P0 | Frontend React en el repositorio del equipo | Login MS0 y listados reales, navegación y errores 401/403/404; **sin secretos en Git** |
| P0 | Completar ciclo de negocio | Orden → visita → atención → evidencia → finalización → actualización de orden |
| P0 | SNS/SQS y eventos | `ParteFinalizado` termina visita y deja historia/estado consistente en MS3; reintentos idempotentes |
| P1 | Carga ficticia directa | 30 000 registros por microservicio repartidos entre 3 tenants, desde EC2 Python/boto3, con reporte (consulta al profesor si MS0 aplica) |
| P1 | UI Agenda/Partes y roles | Formularios conectados; técnico solo sus visitas una vez habilitado el rol en backend |
| P1 | Amplify, documentación y demo | URL pública, evidencia de dos tenants, informe y PPT coherentes con infraestructura real |

## 5. Tenants, roles y fechas

- Empresas ficticias: `CLIMALIMA`, `FRIOSUR`, `TECNINORTE`. Se han probado las dos primeras; TecniNorte y la carga masiva siguen pendientes.
- MS0 acepta `ADMIN`, `COORDINADOR`, `TECNICO`, pero **las APIs actuales MS1–MS5 restringen la mayor parte de operaciones a ADMIN/COORDINADOR**. No simular un login técnico con funcionalidades que no existen.
- La contraseña se verifica en MS0; el token es opaco, distinto en cada login, vence aproximadamente a los **60 minutos** y se revoca en logout. La interfaz debe tratar 401 como sesión inválida.
- Hito oficial de avance y exposición virtual: **14 de noviembre de 2026**; entrega final: **22 de noviembre de 2026, 23:59 (Lima)**; exposición presencial en semana 16, según el plan académico.

## 6. Qué NO hacer

- No pegar secretos AWS Academy, contraseñas, tokens Bearer ni URLs S3 firmadas en repositorios o chats del equipo.
- No incluir `tenant_id` en peticiones de negocio como autoridad. MS1–MS5 obtienen tenant desde el token validado.
- No editar datos DynamoDB directamente desde React. Siempre por API Gateway.
- No cargar miles de registros por las APIs: el docente pidió Python/boto3 desde la VM.
- No actualizar el viejo diagrama diciendo que todos los componentes futuros ya están desplegados. Crear una vista `implementado vs propuesto` para el informe.
