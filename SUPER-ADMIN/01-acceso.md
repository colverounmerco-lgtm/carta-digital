# 01 — Acceso al panel de administración

## Cómo entrar

1. Abre el navegador y ve a `/admin` de tu plataforma:
   - **Local:** http://localhost:5001/admin
   - **Producción:** https://TU-DOMINIO.railway.app/admin

2. Ingresa tu usuario y contraseña.

3. Haz clic en **Entrar**.

> El panel de admin es completamente independiente de los restaurantes.
> Un restaurante registrado NO puede acceder a `/admin` aunque lo intente.

---

## Dónde están las credenciales

Las credenciales viven en el archivo `.env` en la raíz del proyecto:

```
ADMIN_USER=admin
ADMIN_PASSWORD=admin1234
```

**En local:** edita el archivo `.env` directamente.  
**En Railway:** ve a tu proyecto → Variables → busca `ADMIN_USER` y `ADMIN_PASSWORD`.

---

## Cómo cambiar la contraseña

### En local
1. Abre `carta-digital/.env`
2. Cambia la línea `ADMIN_PASSWORD=nueva-contraseña`
3. Reinicia el servidor: cierra la terminal y vuelve a correr `python main.py`

### En Railway (producción)
1. Entra a [railway.app](https://railway.app) → tu proyecto
2. Ve a la pestaña **Variables**
3. Busca `ADMIN_PASSWORD` y edita el valor
4. Railway reinicia el servidor automáticamente

---

## Cerrar sesión

Haz clic en el botón **Cerrar sesión** en la esquina superior derecha del panel.

La sesión de admin es separada de la sesión de restaurante. Puedes tener ambas abiertas al mismo tiempo en el mismo navegador.
