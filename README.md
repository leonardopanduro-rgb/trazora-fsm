# Trazora FSM — Grupo 5

Proyecto final CS2032 Cloud Computing (2026-2).

SaaS multitenant de gestión de servicios técnicos de aire acondicionado desplegado en AWS.

Tenants de demostración: CLIMALIMA, FRIOSUR y TECNINORTE.

Microservicios planeados:
- MS0 usuarios: login, sesiones y autorizador.
- MS1 clientes: clientes y ubicaciones.
- MS2 tecnicos: técnicos y jornadas.
- MS3 ordenes: órdenes de trabajo.
- MS4 agenda: visitas y reservas.
- MS5 partes: partes de trabajo y evidencias.

Tecnologías: Python, Lambda, API Gateway, DynamoDB, React, Amplify, S3, SNS, SQS y Serverless Framework.

ESTADO: Solo estructura inicial y endpoint de prueba HTTP /health. La autenticación y servicios de negocio aún no están implementados.

## Preparación en EC2

    cd /home/ubuntu
    git clone https://github.com/leonardopanduro-rgb/trazora-fsm.git
    cd trazora-fsm
    git status

Si el repositorio es privado, usar autenticación GitHub autorizada sin incorporar tokens a la URL.

## Primer despliegue (solo prueba de salud)

Actualizar las credenciales temporales del laboratorio en ~/.aws/credentials y comprobar:

    aws sts get-caller-identity --region us-east-1

Obtener de IAM el ARN real del rol Lambda autorizado, luego:

    export AWS_PROFILE=default
    export AWS_REGION=us-east-1
    export LAB_ROLE_ARN='ARN_REAL_DEL_ROL'
    cd /home/ubuntu/trazora-fsm/backend/usuarios
    serverless login
    serverless deploy --stage dev --region us-east-1
    serverless info --stage dev --region us-east-1

La API /health es pública solamente para la verificación inicial. No despliega login ni autorización multitenant.

Nunca subir credenciales, contraseñas ni tokens a GitHub. EC2 es una estación de desarrollo, no el alojamiento permanente de las APIs.
