# 03 — Acciones disponibles por restaurante

## 🔍 Ver panel

**Qué hace:** Te mete dentro del panel del restaurante como si fueras el dueño, sin necesitar su contraseña.

**Cuándo usarlo:**
- Un restaurante reporta un problema y necesitas ver qué está pasando
- Quieres verificar que la cuenta está configurada correctamente
- Soporte técnico a un cliente

**Cómo volver al panel de admin:**
- Ve manualmente a `/admin` en el navegador
- O cierra sesión desde el panel del restaurante y entra al admin de nuevo

> ⚠️ Mientras estás "viendo" el panel de un restaurante, tu sesión de admin sigue activa.
> Navegar a `/admin` te regresa inmediatamente sin necesidad de login.

---

## Desactivar / Activar

**Qué hace:**
- **Desactivar:** El restaurante ya no puede iniciar sesión. Sus clientes tampoco pueden hacer pedidos (la carta muestra error).
- **Activar:** Reactiva la cuenta. Todo vuelve a funcionar exactamente igual que antes.

**Cuándo desactivar:**
- El restaurante dejó de pagar (si tienes un modelo de suscripción)
- Se detectó uso inapropiado de la plataforma
- El restaurante pidió pausar su cuenta temporalmente

**Cuándo NO desactivar:**
- Si solo quieres revisar la cuenta — usa "Ver panel" en su lugar
- Si el restaurante tiene pedidos activos — espera a que los resuelva primero

> La desactivación pide confirmación con el nombre del restaurante antes de ejecutarse.

---

## Eliminar

**Qué hace:** Borra permanentemente el restaurante y **todos sus datos**:
- Cuenta y contraseña
- Todos los productos del menú y sus fotos
- Todas las mesas y sus QR
- Todo el historial de órdenes e ingresos

**Esta acción NO se puede deshacer.**

**Cuándo eliminar:**
- El restaurante pidió darse de baja definitivamente
- Una cuenta fue creada por error o con datos falsos
- Limpieza de cuentas inactivas antiguas

> Siempre pide confirmación con el nombre del restaurante antes de ejecutarse.
> Las fotos en Cloudinary NO se eliminan automáticamente — debes borrarlas manualmente desde el panel de Cloudinary si lo deseas.

---

## Resumen rápido

| Situación | Acción recomendada |
|-----------|-------------------|
| Cliente no paga | Desactivar |
| Cliente quiere darse de baja | Eliminar (previa confirmación con el cliente) |
| Cliente reporta un bug | Ver panel → reproducir el problema |
| Cuenta creada por error | Eliminar |
| Cliente quiere pausa temporal | Desactivar → Activar cuando vuelva |
