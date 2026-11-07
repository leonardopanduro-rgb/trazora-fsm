# Trazora FSM — Grupo 5 (CS2032 Cloud Computing 2026-2)

SaaS multitenant de gestión de servicios técnicos de aire acondicionado para **CLIMALIMA**, **FRIOSUR** y **TECNINORTE**. Backend en AWS Lambda + API Gateway, DynamoDB por microservicio, S3 para evidencias, SNS/SQS para eventos. Desarrollo y despliegue con Serverless Framework desde AWS Academy.

## Estado del repositorio

**Hay código funcional preparado para seis microservicios**, pero la presencia de código no demuestra por sí sola el despliegue ni la ejecución de todos sus flujos:

| Servicio | Funciones de código disponibles |
| --- | --- |
| MS0 Usuarios | Login, tokens, autorización y bootstrap |
| MS1 Clientes | Clientes y validaciones por tenant |
| MS2 Técnicos | Técnicos, jornadas y activación/desactivación |
| MS3 Órdenes | Crear, buscar, listar; consumidor de eventos e historial |
| MS4 Agenda | Programar, iniciar, reprogramar y cancelar; consumidor de ParteFinalizado |
| MS5 Partes | Borradores, evidencias S3 y finalizar parte + OUTBOX + publicación SNS |

La integración propuesta de eventos **no usa DynamoDB Streams**. MS5 publica `ParteFinalizado` desde Lambda tras guardar el OUTBOX. SNS envía el mensaje a SQS Agenda y SQS Órdenes. Agenda finaliza la visita y publica `VisitaCompletada`, mientras Órdenes registra historial y actualiza el estado al recibir esa confirmación. Hay INBOX y recuperación manual de OUTBOX mediante boto3.

**Estado actualizado (7/11/2026):** se comprobó mediante capturas del laboratorio **un caso end-to-end exitoso**: MS5 `ParteFinalizado` → SNS → SQS → MS4 visita `FINALIZADA` → MS3 orden `PENDIENTE_DE_CIERRE`. Los dos consumidores manuales están ahora habilitados; las colas SNS/SQS existen fuera del stack `trazora-eventos-dev`. No supone cierre completo, automatización final de los consumidores ni pruebas de todos los tenants. Ver [evidencia y pendientes](docs/ESTADO_INTEGRACION_2026-11-07.md).

### Para continuar

- [Guía de eventos y despliegue seguro en AWS Academy](docs/EDA_SNS_SQS_LABROLE.md)
- [Entrega del frontend React premium y traspaso seguro al repositorio del equipo](docs/TRASPASO_FRONTEND_2026-11-07.md)
- [Notas de integración del backend](docs/INTEGRACION_BACKEND_2026-11-04.md)
- [Finalización de MS5](docs/MS5_FINALIZAR.md)
- [Generador y verificador de datos](scripts/seed/README.md)

**No desplegar `infra/eventos/serverless.yml` sobre los recursos existentes con los mismos nombres.** No activar ambos pares de consumidores SQS. Los mappings nuevos se declaran inicialmente deshabilitados.

## Pruebas locales (sin AWS)

En una terminal de desarrollo con Python 3.10+ y boto3:

```bash
cd ~/trazora-fsm
python3 -m venv ~/.venvs/trazora-tools
~/.venvs/trazora-tools/bin/python -m pip install boto3
PYTHONDONTWRITEBYTECODE=1 ~/.venvs/trazora-tools/bin/python -m unittest discover -s tests -p 'test_*.py' -v
```

La suite de pruebas contiene mocks y no necesita credenciales AWS. Hay además una configuración de GitHub Actions para tests, cuyo resultado debe verificarse en cada commit.

## AWS Academy / LabRole

Comprobar la identidad con `aws sts get-caller-identity --region us-east-1` tras renovar credenciales del laboratorio. Obtener el ARN de `LabRole` y configurarlo mediante variable de entorno para Serverless, según las instrucciones en `docs/EDA_SNS_SQS_LABROLE.md`. Nunca guardar credenciales, contraseñas ni tokens en GitHub.

La máquina EC2 se utiliza para desarrollo, pruebas y carga directa con boto3; las APIs funcionan en Lambda. **No hacer carga masiva por API Gateway.**

## Por completar antes de la entrega

Pruebas y despliegue EDA en dev, permisos y reintentos SNS/SQS, autorización del rol TECNICO para sus visitas, eventos adicionales de Agenda, cierre coordinado de órdenes, frontend React en Amplify, verificación de los volúmenes multitenant y documentación de evidencias. No presentar esos puntos como finalizados sin verificarlos.
