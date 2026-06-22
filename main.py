import os, csv, io
from datetime import datetime, date
from functools import wraps
from pathlib import Path

from flask import (Flask, render_template, request, redirect, url_for,
                   session, flash, make_response)
from sqlalchemy import text, inspect as sa_inspect, func
from dotenv import load_dotenv
import cloudinary, cloudinary.uploader

load_dotenv(Path(__file__).resolve().parent / ".env")
from models import db, Restaurante, Mesa, Producto, Orden, ItemOrden, slugify

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "carta-dev-secret")

# ── Base de datos ──
_db_url = os.getenv("DATABASE_URL", "")
if _db_url.startswith("postgres://"):
    _db_url = _db_url.replace("postgres://", "postgresql+pg8000://", 1)
elif _db_url.startswith("postgresql://") and "+pg8000" not in _db_url:
    _db_url = _db_url.replace("postgresql://", "postgresql+pg8000://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = _db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db.init_app(app)

# ── Cloudinary ──
cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
)

MAX_CANTIDAD = 10


# ── Helpers ──
def restaurante_session():
    rid = session.get("restaurante_id")
    return Restaurante.query.get(rid) if rid else None


def subir_imagen(file_storage, folder="carta_digital"):
    result = cloudinary.uploader.upload(
        file_storage,
        folder=folder,
        transformation=[{"width": 900, "height": 700, "crop": "fill", "quality": "auto:good"}],
    )
    return result["secure_url"]


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("restaurante_id"):
            flash("Inicia sesión primero.", "error")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


@app.context_processor
def ctx():
    return {"restaurante_session": restaurante_session()}


# ── Migraciones runtime ──
def run_migrations():
    insp = sa_inspect(db.engine)
    tables = insp.get_table_names()

    def add_col(table, col, definition):
        cols = [c["name"] for c in insp.get_columns(table)]
        if col not in cols:
            db.session.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {definition}"))
            db.session.commit()

    if "ordenes" in tables:
        add_col("ordenes", "metodo_pago",     "VARCHAR(30)")
        add_col("ordenes", "notas",           "TEXT")
        add_col("ordenes", "solicita_cuenta", "BOOLEAN DEFAULT FALSE")
        add_col("ordenes", "fecha_pago",      "TIMESTAMP")

    if "productos" in tables:
        add_col("productos", "orden_display", "INTEGER DEFAULT 0")

    if "restaurantes" in tables:
        add_col("restaurantes", "descripcion", "TEXT")


with app.app_context():
    db.create_all()
    run_migrations()


# ══════════════════════════════════════════════
#  AUTH
# ══════════════════════════════════════════════

@app.route("/")
def index():
    if session.get("restaurante_id"):
        return redirect(url_for("dashboard"))
    return render_template("landing.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        nombre      = request.form.get("nombre", "").strip()
        email       = request.form.get("email", "").strip().lower()
        pwd         = request.form.get("password", "")
        pwd2        = request.form.get("password2", "")
        whatsapp    = request.form.get("whatsapp", "").strip()
        ciudad      = request.form.get("ciudad", "").strip()
        descripcion = request.form.get("descripcion", "").strip()

        if not all([nombre, email, pwd]):
            flash("Completa todos los campos requeridos.", "error")
            return redirect(url_for("register"))
        if pwd != pwd2:
            flash("Las contraseñas no coinciden.", "error")
            return redirect(url_for("register"))
        if len(pwd) < 6:
            flash("La contraseña debe tener al menos 6 caracteres.", "error")
            return redirect(url_for("register"))
        if Restaurante.query.filter_by(email=email).first():
            flash("Ya existe una cuenta con ese correo.", "error")
            return redirect(url_for("register"))

        base_slug, counter, slug = slugify(nombre), 1, slugify(nombre)
        while Restaurante.query.filter_by(slug=slug).first():
            slug = f"{base_slug}-{counter}"; counter += 1

        logo_url = None
        if "logo" in request.files and request.files["logo"].filename:
            try:
                logo_url = subir_imagen(request.files["logo"], "carta_logos")
            except Exception as e:
                flash(f"Error al subir logo: {e}", "error")
                return redirect(url_for("register"))

        r = Restaurante(nombre=nombre, email=email, slug=slug,
                        whatsapp=whatsapp, ciudad=ciudad,
                        logo_url=logo_url, descripcion=descripcion)
        r.set_password(pwd)
        db.session.add(r)
        db.session.commit()
        session["restaurante_id"] = r.id
        flash(f"¡Bienvenido, {nombre}! Empieza creando tu menú.", "success")
        return redirect(url_for("dashboard"))

    return render_template("auth/register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        pwd   = request.form.get("password", "")
        r = Restaurante.query.filter_by(email=email).first()
        if not r or not r.check_password(pwd):
            flash("Correo o contraseña incorrectos.", "error")
            return redirect(url_for("login"))
        if not r.activo:
            flash("Tu cuenta está desactivada.", "error")
            return redirect(url_for("login"))
        session["restaurante_id"] = r.id
        return redirect(url_for("dashboard"))
    return render_template("auth/login.html")


@app.route("/logout")
def logout():
    session.pop("restaurante_id", None)
    return redirect(url_for("index"))


# ══════════════════════════════════════════════
#  DASHBOARD
# ══════════════════════════════════════════════

@app.route("/dashboard")
@login_required
def dashboard():
    r   = restaurante_session()
    hoy = date.today()

    ordenes_activas = Orden.query.filter(
        Orden.restaurante_id == r.id,
        Orden.estado.in_(["pendiente", "confirmada", "lista"])
    ).order_by(Orden.fecha.desc()).all()

    total_hoy = db.session.query(func.count(Orden.id)).filter(
        Orden.restaurante_id == r.id,
        Orden.estado == "pagada",
        func.date(Orden.fecha) == hoy,
    ).scalar() or 0

    ingresos_hoy = db.session.query(func.sum(Orden.total)).filter(
        Orden.restaurante_id == r.id,
        Orden.estado == "pagada",
        func.date(Orden.fecha) == hoy,
    ).scalar() or 0.0

    cuentas_solicitadas = sum(1 for o in ordenes_activas if o.solicita_cuenta)

    return render_template("restaurante/dashboard.html",
        restaurante=r,
        ordenes_activas=ordenes_activas,
        total_hoy=total_hoy,
        ingresos_hoy=ingresos_hoy,
        cuentas_solicitadas=cuentas_solicitadas,
    )


# ── Acciones sobre órdenes ──

@app.route("/dashboard/orden/<int:oid>/confirmar", methods=["POST"])
@login_required
def confirmar_orden(oid):
    r = restaurante_session()
    o = Orden.query.filter_by(id=oid, restaurante_id=r.id).first_or_404()
    if o.estado == "pendiente":
        o.estado = "confirmada"
        db.session.commit()
    return redirect(url_for("dashboard"))


@app.route("/dashboard/orden/<int:oid>/lista", methods=["POST"])
@login_required
def orden_lista(oid):
    r = restaurante_session()
    o = Orden.query.filter_by(id=oid, restaurante_id=r.id).first_or_404()
    if o.estado == "confirmada":
        o.estado = "lista"
        db.session.commit()
    return redirect(url_for("dashboard"))


@app.route("/dashboard/orden/<int:oid>/pagar", methods=["POST"])
@login_required
def pagar_orden(oid):
    r = restaurante_session()
    o = Orden.query.filter_by(id=oid, restaurante_id=r.id).first_or_404()
    if o.estado == "lista":
        o.estado      = "pagada"
        o.metodo_pago = request.form.get("metodo", "efectivo")
        o.fecha_pago  = datetime.utcnow()
        db.session.commit()
    return redirect(url_for("dashboard"))


@app.route("/dashboard/orden/<int:oid>/cancelar", methods=["POST"])
@login_required
def cancelar_orden(oid):
    r = restaurante_session()
    o = Orden.query.filter_by(id=oid, restaurante_id=r.id).first_or_404()
    if o.estado in ("pendiente", "confirmada"):
        o.estado = "cancelada"
        db.session.commit()
    return redirect(url_for("dashboard"))


# ══════════════════════════════════════════════
#  MENÚ (gestión de productos)
# ══════════════════════════════════════════════

@app.route("/menu")
@login_required
def menu():
    r = restaurante_session()
    productos = Producto.query.filter_by(restaurante_id=r.id).order_by(
        Producto.categoria, Producto.orden_display, Producto.id
    ).all()
    return render_template("restaurante/menu.html", restaurante=r, productos=productos)


@app.route("/menu/agregar", methods=["GET", "POST"])
@login_required
def agregar_producto():
    r = restaurante_session()
    if request.method == "POST":
        nombre      = request.form.get("nombre", "").strip()
        descripcion = request.form.get("descripcion", "").strip()
        categoria   = request.form.get("categoria", "Principal").strip() or "Principal"
        try:
            precio = float(request.form.get("precio", "0"))
        except ValueError:
            flash("Precio inválido.", "error")
            return redirect(url_for("agregar_producto"))

        if not nombre:
            flash("El nombre es requerido.", "error")
            return redirect(url_for("agregar_producto"))

        imagen_url = None
        if "imagen" in request.files and request.files["imagen"].filename:
            try:
                imagen_url = subir_imagen(request.files["imagen"])
            except Exception as e:
                flash(f"Error al subir imagen: {e}", "error")
                return redirect(url_for("agregar_producto"))
        else:
            flash("Debes subir una foto del plato.", "error")
            return redirect(url_for("agregar_producto"))

        db.session.add(Producto(
            restaurante_id=r.id, nombre=nombre, descripcion=descripcion,
            precio=precio, imagen_url=imagen_url, categoria=categoria,
        ))
        db.session.commit()
        flash("Plato agregado al menú.", "success")
        return redirect(url_for("menu"))

    return render_template("restaurante/agregar_producto.html", restaurante=r)


@app.route("/menu/editar/<int:pid>", methods=["GET", "POST"])
@login_required
def editar_producto(pid):
    r = restaurante_session()
    p = Producto.query.filter_by(id=pid, restaurante_id=r.id).first_or_404()

    if request.method == "POST":
        p.nombre      = request.form.get("nombre", p.nombre).strip()
        p.descripcion = request.form.get("descripcion", "").strip()
        p.categoria   = request.form.get("categoria", "Principal").strip() or "Principal"
        p.disponible  = "disponible" in request.form
        try:
            p.precio = float(request.form.get("precio", p.precio))
        except ValueError:
            pass

        if "imagen" in request.files and request.files["imagen"].filename:
            try:
                p.imagen_url = subir_imagen(request.files["imagen"])
            except Exception as e:
                flash(f"Error al subir imagen: {e}", "error")
                return redirect(url_for("editar_producto", pid=pid))

        db.session.commit()
        flash("Plato actualizado.", "success")
        return redirect(url_for("menu"))

    return render_template("restaurante/editar_producto.html", restaurante=r, producto=p)


@app.route("/menu/eliminar/<int:pid>", methods=["POST"])
@login_required
def eliminar_producto(pid):
    r = restaurante_session()
    p = Producto.query.filter_by(id=pid, restaurante_id=r.id).first_or_404()
    db.session.delete(p)
    db.session.commit()
    flash("Plato eliminado.", "success")
    return redirect(url_for("menu"))


@app.route("/menu/toggle/<int:pid>", methods=["POST"])
@login_required
def toggle_producto(pid):
    r = restaurante_session()
    p = Producto.query.filter_by(id=pid, restaurante_id=r.id).first_or_404()
    p.disponible = not p.disponible
    db.session.commit()
    return redirect(url_for("menu"))


# ══════════════════════════════════════════════
#  MESAS
# ══════════════════════════════════════════════

@app.route("/mesas")
@login_required
def mesas():
    r = restaurante_session()
    mesas_list = Mesa.query.filter_by(restaurante_id=r.id).order_by(Mesa.numero).all()
    return render_template("restaurante/mesas.html", restaurante=r, mesas=mesas_list)


@app.route("/mesas/agregar", methods=["POST"])
@login_required
def agregar_mesa():
    r      = restaurante_session()
    nombre = request.form.get("nombre", "").strip()
    ultimo = db.session.query(func.max(Mesa.numero)).filter_by(restaurante_id=r.id).scalar() or 0
    numero = ultimo + 1
    nombre = nombre or f"Mesa {numero}"
    db.session.add(Mesa(restaurante_id=r.id, numero=numero, nombre=nombre, token=Mesa.nuevo_token()))
    db.session.commit()
    flash(f"'{nombre}' creada.", "success")
    return redirect(url_for("mesas"))


@app.route("/mesas/eliminar/<int:mid>", methods=["POST"])
@login_required
def eliminar_mesa(mid):
    r = restaurante_session()
    m = Mesa.query.filter_by(id=mid, restaurante_id=r.id).first_or_404()
    db.session.delete(m)
    db.session.commit()
    flash("Mesa eliminada.", "success")
    return redirect(url_for("mesas"))


# ══════════════════════════════════════════════
#  CARTA PÚBLICA (lo que ve el cliente)
# ══════════════════════════════════════════════

@app.route("/carta/<slug>/<mesa_token>")
def carta(slug, mesa_token):
    r    = Restaurante.query.filter_by(slug=slug, activo=True).first_or_404()
    mesa = Mesa.query.filter_by(token=mesa_token, restaurante_id=r.id, activa=True).first_or_404()

    productos = Producto.query.filter_by(
        restaurante_id=r.id, disponible=True
    ).order_by(Producto.categoria, Producto.orden_display).all()

    categorias, cat_map = [], {}
    for p in productos:
        if p.categoria not in cat_map:
            categorias.append(p.categoria)
            cat_map[p.categoria] = []
        cat_map[p.categoria].append(p)

    carrito = session.get(f"cart_{mesa_token}", {})
    total_carrito  = sum(v["precio"] * v["cantidad"] for v in carrito.values())
    items_carrito  = sum(v["cantidad"] for v in carrito.values())

    return render_template("carta/index.html",
        restaurante=r, mesa=mesa,
        categorias=categorias, cat_map=cat_map,
        carrito=carrito, total_carrito=total_carrito,
        items_carrito=items_carrito, max_cantidad=MAX_CANTIDAD,
    )


@app.route("/carta/<slug>/<mesa_token>/agregar", methods=["POST"])
def carta_agregar(slug, mesa_token):
    r    = Restaurante.query.filter_by(slug=slug, activo=True).first_or_404()
    Mesa.query.filter_by(token=mesa_token, restaurante_id=r.id, activa=True).first_or_404()

    prod_id  = request.form.get("producto_id", type=int)
    cantidad = max(1, min(request.form.get("cantidad", 1, type=int), MAX_CANTIDAD))
    p        = Producto.query.filter_by(id=prod_id, restaurante_id=r.id, disponible=True).first_or_404()

    cart_key = f"cart_{mesa_token}"
    carrito  = session.get(cart_key, {})
    key      = str(prod_id)
    actual   = carrito.get(key, {}).get("cantidad", 0)

    carrito[key] = {
        "nombre":   p.nombre,
        "precio":   p.precio,
        "cantidad": min(actual + cantidad, MAX_CANTIDAD),
        "imagen":   p.imagen_url or "",
    }
    session[cart_key] = carrito
    return redirect(url_for("carta", slug=slug, mesa_token=mesa_token) + "#carrito")


@app.route("/carta/<slug>/<mesa_token>/cambiar/<int:prod_id>", methods=["POST"])
def carta_cambiar(slug, mesa_token, prod_id):
    cart_key = f"cart_{mesa_token}"
    carrito  = session.get(cart_key, {})
    key      = str(prod_id)
    accion   = request.form.get("accion")  # "mas" | "menos" | "quitar"

    if key in carrito:
        if accion == "mas":
            carrito[key]["cantidad"] = min(carrito[key]["cantidad"] + 1, MAX_CANTIDAD)
        elif accion == "menos":
            carrito[key]["cantidad"] -= 1
            if carrito[key]["cantidad"] <= 0:
                del carrito[key]
        elif accion == "quitar":
            del carrito[key]

    session[cart_key] = carrito
    return redirect(url_for("carta", slug=slug, mesa_token=mesa_token) + "#carrito")


@app.route("/carta/<slug>/<mesa_token>/pedido", methods=["POST"])
def hacer_pedido(slug, mesa_token):
    r    = Restaurante.query.filter_by(slug=slug, activo=True).first_or_404()
    mesa = Mesa.query.filter_by(token=mesa_token, restaurante_id=r.id, activa=True).first_or_404()

    cart_key = f"cart_{mesa_token}"
    carrito  = session.get(cart_key, {})
    if not carrito:
        flash("Tu carrito está vacío.", "error")
        return redirect(url_for("carta", slug=slug, mesa_token=mesa_token))

    nombre_cliente = request.form.get("nombre_cliente", "Cliente").strip() or "Cliente"
    notas          = request.form.get("notas", "").strip()

    total, items = 0.0, []
    for pid_str, item in carrito.items():
        p = Producto.query.filter_by(id=int(pid_str), restaurante_id=r.id, disponible=True).first()
        if not p:
            continue
        cant     = max(1, min(item["cantidad"], MAX_CANTIDAD))
        subtotal = round(p.precio * cant, 2)
        total   += subtotal
        items.append(ItemOrden(
            producto_id=p.id, cantidad=cant,
            precio_unitario=p.precio, subtotal=subtotal,
        ))

    if not items:
        flash("No hay productos disponibles en tu pedido.", "error")
        return redirect(url_for("carta", slug=slug, mesa_token=mesa_token))

    orden = Orden(
        restaurante_id=r.id, mesa_id=mesa.id,
        token=Orden.nuevo_token(),
        nombre_cliente=nombre_cliente,
        total=round(total, 2), notas=notas,
    )
    db.session.add(orden)
    db.session.flush()
    for item in items:
        item.orden_id = orden.id
        db.session.add(item)
    db.session.commit()

    session.pop(cart_key, None)
    return redirect(url_for("estado_orden", token=orden.token))


# ══════════════════════════════════════════════
#  SEGUIMIENTO DE ORDEN (cliente)
# ══════════════════════════════════════════════

@app.route("/orden/<token>")
def estado_orden(token):
    orden = Orden.query.filter_by(token=token).first_or_404()
    return render_template("carta/orden.html", orden=orden, restaurante=orden.restaurante)


@app.route("/orden/<token>/cuenta", methods=["POST"])
def solicitar_cuenta(token):
    orden = Orden.query.filter_by(token=token).first_or_404()
    if orden.estado == "lista":
        orden.solicita_cuenta = True
        db.session.commit()
    return redirect(url_for("estado_orden", token=token))


# ══════════════════════════════════════════════
#  REPORTES
# ══════════════════════════════════════════════

@app.route("/reportes")
@login_required
def reportes():
    r   = restaurante_session()
    hoy = date.today()

    # Resumen mensual de los últimos 12 meses
    resumen_mensual = db.session.query(
        func.extract("year",  Orden.fecha).label("anio"),
        func.extract("month", Orden.fecha).label("mes"),
        func.count(Orden.id).label("ordenes"),
        func.sum(Orden.total).label("total"),
    ).filter(
        Orden.restaurante_id == r.id,
        Orden.estado == "pagada",
    ).group_by("anio", "mes").order_by("anio", "mes").all()

    return render_template("restaurante/reportes.html",
        restaurante=r, hoy=hoy, resumen_mensual=resumen_mensual)


@app.route("/reportes/descargar")
@login_required
def descargar_reporte():
    r         = restaurante_session()
    tipo      = request.args.get("tipo", "diario")
    fecha_str = request.args.get("fecha", date.today().isoformat())

    try:
        fecha_ref = date.fromisoformat(fecha_str)
    except ValueError:
        fecha_ref = date.today()

    if tipo == "diario":
        ordenes = Orden.query.filter(
            Orden.restaurante_id == r.id,
            Orden.estado == "pagada",
            func.date(Orden.fecha) == fecha_ref,
        ).order_by(Orden.fecha).all()
        nombre_archivo = f"reporte_diario_{fecha_ref}.csv"
    else:
        ordenes = Orden.query.filter(
            Orden.restaurante_id == r.id,
            Orden.estado == "pagada",
            func.extract("year",  Orden.fecha) == fecha_ref.year,
            func.extract("month", Orden.fecha) == fecha_ref.month,
        ).order_by(Orden.fecha).all()
        nombre_archivo = f"reporte_mensual_{fecha_ref.year}_{fecha_ref.month:02d}.csv"

    output = io.StringIO()
    w = csv.writer(output)
    w.writerow(["Fecha", "Hora", "# Orden", "Mesa", "Cliente",
                "Producto", "Cantidad", "Precio Unit.", "Subtotal",
                "Total Orden", "Método Pago"])

    for o in ordenes:
        for item in o.items:
            w.writerow([
                o.fecha.strftime("%d/%m/%Y"),
                o.fecha.strftime("%H:%M"),
                o.id,
                o.mesa.nombre if o.mesa else "—",
                o.nombre_cliente,
                item.producto.nombre if item.producto else "—",
                item.cantidad,
                f"{item.precio_unitario:.2f}",
                f"{item.subtotal:.2f}",
                f"{o.total:.2f}",
                o.metodo_pago or "—",
            ])

    output.seek(0)
    resp = make_response("﻿" + output.getvalue())  # BOM for Excel
    resp.headers["Content-Disposition"] = f"attachment; filename={nombre_archivo}"
    resp.headers["Content-Type"] = "text/csv; charset=utf-8"
    return resp


# ══════════════════════════════════════════════
#  PERFIL
# ══════════════════════════════════════════════

@app.route("/perfil", methods=["GET", "POST"])
@login_required
def perfil():
    r = restaurante_session()
    if request.method == "POST":
        r.nombre      = request.form.get("nombre", r.nombre).strip()
        r.whatsapp    = request.form.get("whatsapp", "").strip()
        r.ciudad      = request.form.get("ciudad", "").strip()
        r.descripcion = request.form.get("descripcion", "").strip()

        pwd = request.form.get("password", "")
        if pwd:
            if len(pwd) < 6:
                flash("La contraseña debe tener al menos 6 caracteres.", "error")
                return redirect(url_for("perfil"))
            r.set_password(pwd)

        if "logo" in request.files and request.files["logo"].filename:
            try:
                r.logo_url = subir_imagen(request.files["logo"], "carta_logos")
            except Exception as e:
                flash(f"Error al subir logo: {e}", "error")
                return redirect(url_for("perfil"))

        db.session.commit()
        flash("Perfil actualizado.", "success")
        return redirect(url_for("perfil"))

    return render_template("restaurante/perfil.html", restaurante=r)


if __name__ == "__main__":
    app.run(debug=True, port=5001)
