# 04 — Configuración en producción (Railway)

## Variables de entorno que debes tener en Railway

Ve a tu proyecto en Railway → pestaña **Variables** y confirma que estas existen:

| Variable | Valor esperado | Obligatoria |
|----------|---------------|-------------|
| `SECRET_KEY` | Cadena aleatoria larga (mínimo 32 caracteres) | ✅ Sí |
| `DATABASE_URL` | URL de tu base de datos PostgreSQL (Railway la genera automáticamente) | ✅ Sí |
| `CLOUDINARY_CLOUD_NAME` | Tu cloud name de Cloudinary | ✅ Sí |
| `CLOUDINARY_API_KEY` | Tu API key de Cloudinary | ✅ Sí |
| `CLOUDINARY_API_SECRET` | Tu API secret de Cloudinary | ✅ Sí |
| `ADMIN_USER` | Tu usuario admin (no uses "admin") | ✅ Sí |
| `ADMIN_PASSWORD` | Contraseña segura (mínimo 12 caracteres) | ✅ Sí |

---

## Cómo generar una SECRET_KEY segura

Abre una terminal y corre:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Copia el resultado y pégalo en la variable `SECRET_KEY` de Railway.

> Si cambias `SECRET_KEY` en producción, todas las sesiones activas (restaurantes logueados) se cerrarán automáticamente. Es normal y seguro.

---

## Base de datos en Railway

Railway puede crear una base de datos PostgreSQL gratis dentro de tu proyecto:

1. En tu proyecto de Railway → **+ New** → **Database** → **PostgreSQL**
2. Railway genera automáticamente la variable `DATABASE_URL` y la conecta a tu app
3. No necesitas hacer nada más — la app crea las tablas sola al arrancar

### Hacer backup de la base de datos

Desde Railway puedes descargar un backup:
1. Click en el servicio PostgreSQL de tu proyecto
2. Pestaña **Data** → **Backups**
3. Descarga el archivo `.sql`

Guarda este archivo en un lugar seguro periódicamente (al menos una vez por semana).

---

## Subida de imágenes (Cloudinary)

Las fotos de los platos se suben a Cloudinary. Están organizadas así:

```
carta_digital/      ← fotos de platos
carta_logos/        ← logos de restaurantes
```

Para ver o eliminar fotos, entra a:
[cloudinary.com](https://cloudinary.com) → **Media Library** → carpeta `carta_digital`

> Las fotos de restaurantes eliminados desde el panel de admin NO se borran de Cloudinary automáticamente. Debes hacerlo manualmente si quieres liberar espacio.

---

## Cómo ver los logs en Railway (si algo falla)

1. Ve a Railway → tu proyecto → el servicio de la app
2. Pestaña **Logs**
3. Busca líneas que digan `ERROR` o `Traceback`

Si ves un error que no entiendes, copia el texto completo y consulta con el desarrollador.

---

## Dominio personalizado

Para usar `menu.turestaurante.com` en lugar del dominio de Railway:

1. Railway → tu proyecto → pestaña **Settings** → **Domains** → **+ Custom Domain**
2. Escribe tu dominio
3. Railway te da un registro CNAME que debes agregar en tu proveedor de DNS (GoDaddy, Cloudflare, etc.)
4. Espera entre 10 minutos y 24 horas para que el DNS se propague
