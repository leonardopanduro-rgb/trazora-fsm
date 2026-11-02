# Restablecer contraseña de un ADMIN (solo entorno dev)

Requisito: usar la EC2 de desarrollo con credenciales AWS Academy válidas y autorizadas; **no funciona desde Postman** ni requiere borrar o crear de nuevo la cuenta.

**Orden importante:** primero actualizar la Lambda para activar la comprobación de versión de credenciales; después ejecutar el cambio de contraseña. Así los tokens anteriores quedan invalidados.

Desde Ubuntu:

```bash
cd ~/trazora-fsm
git pull --ff-only
python3 -m py_compile backend/usuarios/handler.py backend/usuarios/security.py scripts/bootstrap/restablecer_password.py
cd backend/usuarios
export LAB_ROLE_ARN=$(aws iam get-role --role-name LabRole --query 'Role.Arn' --output text)
serverless deploy --stage dev --region us-east-1
cd ~/trazora-fsm
python3 scripts/bootstrap/restablecer_password.py --tenant FRIOSUR --email admin-frio@example.com
```

Al ejecutarlo confirma el tenant y escribe dos veces una contraseña **nueva** (12 a 128 caracteres) sin espacios añadidos accidentalmente. El script muestra la cuenta AWS, región, tabla, tenant y correo para que verifiques el destino. No imprime tu contraseña ni el hash, no crea usuarios, y no modifica el correo ni el rol.

Comprueba luego:

```bash
python3 scripts/pruebas/diagnosticar_ms0.py --tenant FRIOSUR --email admin-frio@example.com
python3 scripts/pruebas/probar_ms0.py
```

La primera prueba debe indicar que la nueva contraseña coincide, y la segunda debería devolver 200 en login, perfil y logout, y 401 al reutilizar el token revocado.

Si faltan credenciales, renueva ~/.aws/credentials desde el laboratorio. Este procedimiento es una herramienta **de administración local de desarrollo**, no un endpoint de autoservicio ni un flujo de recuperación por correo para usuarios finales. La rotación incrementa credential_version del usuario y el autorizador rechaza tokens cuya versión no coincida.
