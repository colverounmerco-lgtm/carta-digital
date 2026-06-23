# 02 — Qué ves en el panel

## Tarjetas de resumen (parte superior)

Al entrar al panel, lo primero que ves son 4 cifras globales de toda la plataforma:

| Tarjeta | Qué significa |
|---------|--------------|
| **Restaurantes totales** | Cuántas cuentas existen (incluyendo la demo) |
| **Activos** | Cuántas cuentas están habilitadas para operar |
| **Órdenes totales** | Suma de todos los pedidos de todos los restaurantes |
| **Ingresos totales procesados** | Suma del dinero cobrado en órdenes marcadas como "pagadas" |

> Los ingresos son los que los restaurantes han marcado como cobrados dentro de la app.
> No incluye efectivo o transferencias que no hayan sido registradas en el sistema.

---

## Tabla de restaurantes

Cada fila es un restaurante. Las columnas son:

| Columna | Descripción |
|---------|-------------|
| **Restaurante** | Nombre y fecha en que se registró |
| **Correo** | Email con el que se registró (es su usuario de login) |
| **Ciudad** | Ciudad que ingresaron al registrarse |
| **Órdenes** | Total histórico de pedidos. El número naranja indica cuántos hizo hoy |
| **Ingresos** | Total de dinero procesado como pagado |
| **Estado** | `Activo` (verde), `Inactivo` (rojo) o `DEMO` (naranja) |
| **Acciones** | Botones para gestionar la cuenta |

---

## Significado de los estados

- **Activo (verde):** El restaurante puede iniciar sesión y recibir pedidos normalmente.
- **Inactivo (rojo):** La cuenta está bloqueada. Si intenta entrar, verá el mensaje "Tu cuenta está desactivada".
- **DEMO (naranja):** Es la cuenta de demostración que viene por defecto. No se puede desactivar ni eliminar desde el panel para protegerla.

---

## La cuenta DEMO

La plataforma incluye un restaurante de demostración llamado **El Rincón Criollo** con:
- 13 platos de ejemplo con fotos
- 8 mesas con sus QR
- Acceso en: `/demo`

Esta cuenta se usa para que clientes potenciales prueben la plataforma antes de registrarse. No la elimines.
