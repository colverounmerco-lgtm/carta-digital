# 05 — Seguridad de la plataforma

## Lo más importante (haz esto antes de lanzar)

- [ ] Cambia `ADMIN_PASSWORD` por una contraseña de al menos 12 caracteres
- [ ] Cambia `ADMIN_USER` por algo que no sea "admin"
- [ ] Genera una `SECRET_KEY` aleatoria (ver `04-produccion.md`)
- [ ] Nunca compartas el archivo `.env` por WhatsApp, correo o chat
- [ ] El archivo `.env` está en `.gitignore` — nunca lo subas a GitHub

---

## Reglas de contraseñas

| Variable | Mínimo recomendado | Ejemplo de contraseña fuerte |
|----------|-------------------|------------------------------|
| `ADMIN_PASSWORD` | 12 caracteres, mezcla letras, números y símbolos | `Carta#2026$Adm` |
| `SECRET_KEY` | 64 caracteres aleatorios | generado con `secrets.token_hex(32)` |

---

## Qué puede y qué no puede hacer un restaurante

Un restaurante registrado **puede:**
- Ver y gestionar su propio menú y mesas
- Ver solo sus propias órdenes
- Descargar solo sus propios reportes

Un restaurante **NO puede:**
- Ver datos de otros restaurantes
- Acceder al panel `/admin`
- Ver tus credenciales de admin
- Modificar su estado (activo/inactivo)

---

## Acceso físico al servidor (Railway)

Solo tú debes tener acceso a la cuenta de Railway donde corre la app. Si en algún momento trabajas con un desarrollador externo:

1. Crea una cuenta de Railway separada para él con acceso limitado
2. O compártele solo los logs, no las variables de entorno
3. Una vez termine el trabajo, revoca su acceso

---

## Qué hacer si sospechas que alguien accedió sin permiso

1. **Cambia inmediatamente** `ADMIN_PASSWORD` y `SECRET_KEY` en Railway
2. Revisa en Railway → Logs si hay accesos sospechosos a `/admin`
3. Revisa si algún restaurante fue desactivado o eliminado sin tu autorización
4. Si se comprometieron credenciales de Cloudinary, regéneralas en cloudinary.com

---

## Datos que maneja la plataforma

La app almacena:
- Nombre y correo de los restaurantes (no se almacenan contraseñas en texto plano, solo hashes seguros)
- Nombre de los clientes que hacen pedidos
- Historial de pedidos y montos

**La plataforma NO almacena:**
- Datos de tarjetas de crédito
- Contraseñas de clientes (los clientes no tienen cuenta)
- Información bancaria de ningún tipo

---

## Privacidad y los restaurantes

Cuando un restaurante te contacte pidiendo sus datos, tienes dos opciones:
- Descargar su reporte CSV desde su panel (`/reportes`)
- Exportar su historial directo desde la base de datos en Railway

Si un restaurante quiere eliminar su cuenta y todos sus datos, usa el botón **Eliminar** del panel de admin. Eso borra todo excepto las fotos en Cloudinary (que debes eliminar manualmente).
