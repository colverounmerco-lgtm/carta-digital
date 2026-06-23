# 06 — Configuración de correo (Gmail)

## Credenciales actuales

| Variable | Valor |
|----------|-------|
| `SMTP_HOST` | smtp.gmail.com |
| `SMTP_PORT` | 587 |
| `SMTP_USER` | cartadigital6@gmail.com |
| `SMTP_PASS` | nihv zivu qkfn tpbw |

## Para qué se usa

El correo `cartadigital6@gmail.com` es el remitente de todos los emails automáticos de la plataforma:

- Código de verificación al registrarse
- Código de recuperación de contraseña
- Reenvío de código si el usuario lo solicita

## Si la clave deja de funcionar

Las contraseñas de aplicación de Google pueden revocarse o expirar. Si los correos dejan de llegar:

1. Ve a [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
2. Revoca la clave anterior
3. Genera una nueva con nombre `Carta Digital`
4. Actualiza `SMTP_PASS` en el `.env` local y en Railway

## En Railway (producción)

Agrega estas variables en Railway → tu proyecto → Variables:

```
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=cartadigital6@gmail.com
SMTP_PASS=nihv zivu qkfn tpbw
```
