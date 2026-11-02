# Fase 1 — Preparación y arquitectura

## Preparación
- Máquina EC2 de desarrollo habilitada por CloudFormation.
- Node, npm, Python, Git, AWS CLI y Serverless Framework comprobados.
- AWS Academy: credenciales temporales solo en la EC2.
- Repositorio GitHub y estructura de microservicios.

## Siguientes objetivos
1. Clonar en EC2.
2. Verificar el ARN real del rol de Lambda.
3. Desplegar el endpoint de salud de MS0.
4. Validar respuesta de API Gateway.
5. Diseñar el contrato de login y autorización multitenant antes de publicar rutas de negocio.

## Arquitectura acordada
- Empresas: CLIMALIMA, FRIOSUR, TECNINORTE.
- Seis microservicios con persistencia propia DynamoDB.
- Frontend React en Amplify.
- Backend Python en Lambda expuesto por API Gateway.
- Evidencias S3 y eventos SNS/SQS posteriores.
- Las peticiones de negocio obtienen tenant_id del token validado y no de campos arbitrarios enviados desde el navegador.
- La carga masiva será Python/boto3 desde EC2, no API REST.

Pendiente: confirmar con el docente si el volumen mínimo de 30 000 registros también aplica al MS0 Usuarios.
