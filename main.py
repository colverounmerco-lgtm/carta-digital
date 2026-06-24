import os, csv, io, random, smtplib
from datetime import datetime, date, time, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from functools import wraps
from pathlib import Path

EC_OFFSET = timedelta(hours=-5)   # Ecuador UTC-5, sin horario de verano

from flask import (Flask, render_template, request, redirect, url_for,
                   session, flash, make_response)
from sqlalchemy import text, inspect as sa_inspect, func
from dotenv import load_dotenv
import cloudinary, cloudinary.uploader

load_dotenv(Path(__file__).resolve().parent / ".env")
from models import db, Restaurante, Mesa, Producto, Orden, ItemOrden, MensajeSoporte, CodigoVerificacion, MetodoPago, slugify

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "carta-dev-secret")

# ── Base de datos ──
_db_url = os.getenv("DATABASE_URL", "sqlite:///carta_local.db").strip()
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
CODIGO_TTL   = 15  # minutos
TRIAL_DIAS   = 8

PLANES = {
    "mensual": {
        "nombre": "Mensual",
        "base":   40.00,
        "iva":     6.00,
        "total":  46.00,
        "dias":   30,
        "desc":   "Facturado cada mes",
    },
    "anual": {
        "nombre": "Anual",
        "base":   365.00,
        "iva":    54.75,
        "total":  419.75,
        "dias":   365,
        "desc":   "Pagas solo $35.41/mes",
    },
}


def plan_vigente(r):
    """True si el restaurante tiene acceso activo."""
    if not r:
        return False
    if not r.plan_vence:
        return True
    return datetime.utcnow() <= r.plan_vence


def dias_plan(r):
    """Días restantes del plan (None si no hay fecha de vencimiento)."""
    if not r or not r.plan_vence:
        return None
    delta = r.plan_vence - datetime.utcnow()
    return max(0, delta.days)


def _crear_metodos_default(restaurante_id):
    defaults = [("💵", "Efectivo", 0), ("💳", "Tarjeta", 1), ("📲", "Transferencia", 2), ("/static/img/deuna.svg", "Deuna!", 3)]
    for icono, nombre, orden in defaults:
        db.session.add(MetodoPago(
            restaurante_id=restaurante_id, nombre=nombre,
            icono=icono, orden_display=orden
        ))


def inicio_fin_dia_ec():
    """Devuelve (inicio, fin) del día actual en Ecuador como datetimes UTC."""
    ec_hoy = (datetime.utcnow() + EC_OFFSET).date()
    inicio = datetime.combine(ec_hoy, time.min) - EC_OFFSET
    fin    = datetime.combine(ec_hoy, time.max) - EC_OFFSET
    return inicio, fin


def get_client_ip():
    """Devuelve la IP real del cliente, pasando por proxies de Railway/nginx."""
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.remote_addr


# ── Email ──
def enviar_email(destinatario, asunto, cuerpo_html):
    # Prioridad 1: Resend API (funciona en Railway y cualquier cloud)
    resend_key = os.getenv("RESEND_API_KEY", "")
    if resend_key:
        import urllib.request, json as _json
        payload = _json.dumps({
            "from":    os.getenv("RESEND_FROM", "Carta Digital <noreply@cartadigital.app>"),
            "to":      [destinatario],
            "subject": asunto,
            "html":    cuerpo_html,
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.resend.com/emails",
            data=payload,
            headers={
                "Authorization": f"Bearer {resend_key}",
                "Content-Type":  "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            print(f"[EMAIL OK → {destinatario}] {asunto} (Resend {resp.status})")
        return

    # Prioridad 2: SMTP directo (funciona en local)
    host = os.getenv("SMTP_HOST", "")
    user = os.getenv("SMTP_USER", "")
    pwd  = os.getenv("SMTP_PASS", "")
    port = int(os.getenv("SMTP_PORT", "587"))

    if not all([host, user, pwd]):
        print(f"\n[EMAIL → {destinatario}] {asunto}\n{cuerpo_html}\n")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = asunto
    msg["From"]    = f"Carta Digital <{user}>"
    msg["To"]      = destinatario
    msg.attach(MIMEText(cuerpo_html, "html", "utf-8"))

    with smtplib.SMTP(host, port, timeout=15) as srv:
        srv.ehlo()
        srv.starttls()
        srv.login(user, pwd)
        srv.sendmail(user, destinatario, msg.as_string())
        print(f"[EMAIL OK → {destinatario}] {asunto}")


def generar_codigo():
    return str(random.randint(100000, 999999))


def crear_codigo(email, tipo):
    # Invalida códigos anteriores del mismo tipo
    CodigoVerificacion.query.filter_by(email=email, tipo=tipo, usado=False).update({"usado": True})
    codigo = generar_codigo()
    db.session.add(CodigoVerificacion(
        email=email, codigo=codigo, tipo=tipo,
        expira=datetime.utcnow() + timedelta(minutes=CODIGO_TTL)
    ))
    db.session.commit()
    return codigo


def validar_codigo(email, codigo, tipo):
    c = CodigoVerificacion.query.filter_by(
        email=email, codigo=codigo, tipo=tipo, usado=False
    ).first()
    if not c or datetime.utcnow() > c.expira:
        return False
    c.usado = True
    db.session.commit()
    return True


# ── Helpers ──
def restaurante_session():
    rid = session.get("restaurante_id")
    return Restaurante.query.get(rid) if rid else None


def subir_imagen(file_storage, folder="carta_digital"):
    # Fallback local cuando Cloudinary no está configurado
    if os.getenv("CLOUDINARY_CLOUD_NAME", "") in ("", "placeholder"):
        import uuid
        from werkzeug.utils import secure_filename
        ext      = Path(file_storage.filename).suffix.lower() or ".jpg"
        filename = f"{uuid.uuid4().hex}{ext}"
        upload_dir = Path(__file__).parent / "static" / "uploads"
        upload_dir.mkdir(exist_ok=True)
        file_storage.save(upload_dir / filename)
        return f"/static/uploads/{filename}"

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


def plan_requerido(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        r = restaurante_session()
        if r and not plan_vigente(r):
            vencido_hace = (datetime.utcnow() - r.plan_vence).days if r.plan_vence else 0
            return render_template("auth/plan_vencido.html",
                                   restaurante=r, vencido_hace=vencido_hace)
        return f(*args, **kwargs)
    return decorated


@app.context_processor
def ctx():
    return {
        "restaurante_session": restaurante_session(),
        "now": datetime.utcnow,
    }


@app.template_filter("ec_time")
def ec_time_filter(dt, fmt="%d/%m/%Y %H:%M"):
    if not dt:
        return ""
    return (dt + EC_OFFSET).strftime(fmt)


# ── Migraciones runtime ──
def run_migrations():
    insp = sa_inspect(db.engine)
    tables = insp.get_table_names()

    def add_col(table, col, definition):
        cols = [c["name"] for c in insp.get_columns(table)]
        if col not in cols:
            db.session.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {definition}"))
            db.session.commit()

    if "metodos_pago" in tables:
        # Ampliar icono para soportar URLs de imagen además de emojis
        db.session.execute(text("ALTER TABLE metodos_pago ALTER COLUMN icono TYPE VARCHAR(300)"))
        db.session.commit()

    if "ordenes" in tables:
        add_col("ordenes", "metodo_pago",      "VARCHAR(30)")
        add_col("ordenes", "notas",            "TEXT")
        add_col("ordenes", "solicita_cuenta",  "BOOLEAN DEFAULT FALSE")
        add_col("ordenes", "metodo_preferido", "VARCHAR(30)")
        add_col("ordenes", "fecha_pago",       "TIMESTAMP")

    if "mesas" in tables:
        add_col("mesas", "abierta", "BOOLEAN DEFAULT FALSE")
        # Cerrar todas las mesas sin orden activa (limpieza de estado inicial)
        db.session.execute(text(
            "UPDATE mesas SET abierta = FALSE "
            "WHERE id NOT IN ("
            "  SELECT DISTINCT mesa_id FROM ordenes "
            "  WHERE estado IN ('pendiente','confirmada','lista')"
            ")"
        ))
        db.session.commit()

    if "productos" in tables:
        add_col("productos", "orden_display", "INTEGER DEFAULT 0")

    if "restaurantes" in tables:
        add_col("restaurantes", "descripcion",      "TEXT")
        add_col("restaurantes", "email_verificado", "BOOLEAN DEFAULT FALSE")
        add_col("restaurantes", "plan",             "VARCHAR(20) DEFAULT 'trial'")
        add_col("restaurantes", "plan_inicio",      "TIMESTAMP")
        add_col("restaurantes", "plan_vence",       "TIMESTAMP")
        add_col("restaurantes", "ip_red",           "VARCHAR(50)")
        add_col("restaurantes", "restringir_red",   "BOOLEAN DEFAULT TRUE")

    # Crear métodos de pago por defecto para restaurantes existentes
    for r in Restaurante.query.all():
        if MetodoPago.query.filter_by(restaurante_id=r.id).count() == 0:
            _crear_metodos_default(r.id)
        # Añadir Deuna! si el restaurante no lo tiene aún
        if not MetodoPago.query.filter_by(restaurante_id=r.id, nombre="Deuna!").first():
            ultimo = MetodoPago.query.filter_by(restaurante_id=r.id).count()
            db.session.add(MetodoPago(restaurante_id=r.id, nombre="Deuna!", icono="/static/img/deuna.svg", orden_display=ultimo))
        # Asignar trial a restaurantes sin plan/vencimiento
        if not r.plan:
            r.plan = 'trial'
        if not r.plan_vence:
            base = r.fecha_registro or datetime.utcnow()
            r.plan_vence = base + timedelta(days=TRIAL_DIAS)
    db.session.commit()


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

        skip_verificacion = os.getenv("SKIP_EMAIL_VERIFICATION", "false").lower() == "true"

        r = Restaurante(nombre=nombre, email=email, slug=slug,
                        whatsapp=whatsapp, ciudad=ciudad,
                        logo_url=logo_url, descripcion=descripcion,
                        email_verificado=skip_verificacion)
        r.set_password(pwd)
        db.session.add(r)
        db.session.flush()
        _crear_metodos_default(r.id)
        db.session.commit()

        if skip_verificacion:
            session["restaurante_id"] = r.id
            flash(f"¡Bienvenido, {r.nombre}! Empieza creando tu menú.", "success")
            return redirect(url_for("dashboard"))

        codigo = crear_codigo(email, "registro")
        try:
            enviar_email(email, "Verifica tu cuenta — Carta Digital",
                f"""<div style="font-family:Inter,sans-serif;max-width:480px;margin:0 auto;padding:2rem">
                <h2 style="color:#F97316">¡Bienvenido a Carta Digital!</h2>
                <p>Usa este código para verificar tu cuenta:</p>
                <div style="font-size:2.5rem;font-weight:900;letter-spacing:0.5rem;
                            text-align:center;padding:1.5rem;background:#F9FAFB;
                            border-radius:12px;margin:1.5rem 0;color:#1C1C1E">
                  {codigo}
                </div>
                <p style="color:#6B7280;font-size:0.85rem">
                  Este código expira en {CODIGO_TTL} minutos.<br>
                  Si no creaste esta cuenta, ignora este correo.
                </p></div>""")
        except Exception as e:
            print(f"[EMAIL ERROR] {e}")

        session["verificar_email"] = email
        flash("Te enviamos un código de verificación a tu correo.", "info")
        return redirect(url_for("verificar_email"))

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
        if not r.email_verificado:
            codigo = crear_codigo(email, "registro")
            try:
                enviar_email(email, "Verifica tu cuenta — Carta Digital",
                    f"""<div style="font-family:Inter,sans-serif;max-width:480px;margin:0 auto;padding:2rem">
                    <h2 style="color:#F97316">Verifica tu cuenta</h2>
                    <p>Tu cuenta aún no está verificada. Usa este código:</p>
                    <div style="font-size:2.5rem;font-weight:900;letter-spacing:0.5rem;
                                text-align:center;padding:1.5rem;background:#F9FAFB;
                                border-radius:12px;margin:1.5rem 0;color:#1C1C1E">
                      {codigo}
                    </div>
                    <p style="color:#6B7280;font-size:0.85rem">Expira en {CODIGO_TTL} minutos.</p>
                    </div>""")
            except Exception as e:
                print(f"[EMAIL ERROR] {e}")
            session["verificar_email"] = email
            flash("Verifica tu correo antes de entrar.", "error")
            return redirect(url_for("verificar_email"))
        session["restaurante_id"] = r.id
        return redirect(url_for("dashboard"))
    return render_template("auth/login.html")


@app.route("/logout")
def logout():
    session.pop("restaurante_id", None)
    return redirect(url_for("index"))


@app.route("/verificar-email", methods=["GET", "POST"])
def verificar_email():
    email = session.get("verificar_email")
    if not email:
        return redirect(url_for("login"))

    if request.method == "POST":
        codigo = request.form.get("codigo", "").strip()
        if validar_codigo(email, codigo, "registro"):
            r = Restaurante.query.filter_by(email=email).first()
            if r:
                r.email_verificado = True
                db.session.commit()
                session.pop("verificar_email", None)
                session["restaurante_id"] = r.id
                flash(f"¡Bienvenido, {r.nombre}! Empieza creando tu menú.", "success")
                return redirect(url_for("dashboard"))
        flash("Código incorrecto o expirado.", "error")
        return redirect(url_for("verificar_email"))

    return render_template("auth/verificar_email.html", email=email)


@app.route("/verificar-email/reenviar", methods=["POST"])
def reenviar_codigo_registro():
    email = session.get("verificar_email")
    if not email:
        return redirect(url_for("login"))
    codigo = crear_codigo(email, "registro")
    try:
        enviar_email(email, "Tu nuevo código — Carta Digital",
            f"""<div style="font-family:Inter,sans-serif;max-width:480px;margin:0 auto;padding:2rem">
            <h2 style="color:#F97316">Nuevo código de verificación</h2>
            <div style="font-size:2.5rem;font-weight:900;letter-spacing:0.5rem;
                        text-align:center;padding:1.5rem;background:#F9FAFB;
                        border-radius:12px;margin:1.5rem 0;color:#1C1C1E">
              {codigo}
            </div>
            <p style="color:#6B7280;font-size:0.85rem">Expira en {CODIGO_TTL} minutos.</p>
            </div>""")
        flash("Te enviamos un nuevo código.", "success")
    except Exception as e:
        print(f"[EMAIL ERROR] {e}")
        flash("Error al enviar el correo. Intenta de nuevo.", "error")
    return redirect(url_for("verificar_email"))


@app.route("/recuperar", methods=["GET", "POST"])
def recuperar():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        r = Restaurante.query.filter_by(email=email).first()
        if r:
            codigo = crear_codigo(email, "reset")
            try:
                enviar_email(email, "Recupera tu contraseña — Carta Digital",
                    f"""<div style="font-family:Inter,sans-serif;max-width:480px;margin:0 auto;padding:2rem">
                    <h2 style="color:#F97316">Recuperar contraseña</h2>
                    <p>Usa este código para crear una nueva contraseña:</p>
                    <div style="font-size:2.5rem;font-weight:900;letter-spacing:0.5rem;
                                text-align:center;padding:1.5rem;background:#F9FAFB;
                                border-radius:12px;margin:1.5rem 0;color:#1C1C1E">
                      {codigo}
                    </div>
                    <p style="color:#6B7280;font-size:0.85rem">
                      Expira en {CODIGO_TTL} minutos.<br>
                      Si no solicitaste esto, ignora este correo.
                    </p></div>""")
            except Exception as e:
                print(f"[EMAIL ERROR] {e}")
        # Siempre mostramos el mismo mensaje para no revelar si el email existe
        session["reset_email"] = email
        flash("Si ese correo está registrado, recibirás el código en breve.", "info")
        return redirect(url_for("recuperar_codigo"))
    return render_template("auth/recuperar.html")


@app.route("/recuperar/codigo", methods=["GET", "POST"])
def recuperar_codigo():
    email = session.get("reset_email")
    if not email:
        return redirect(url_for("recuperar"))

    if request.method == "POST":
        codigo = request.form.get("codigo", "").strip()
        pwd    = request.form.get("password", "")
        pwd2   = request.form.get("password2", "")

        if not codigo:
            flash("Ingresa el código.", "error")
            return redirect(url_for("recuperar_codigo"))
        if pwd != pwd2:
            flash("Las contraseñas no coinciden.", "error")
            return redirect(url_for("recuperar_codigo"))
        if len(pwd) < 6:
            flash("La contraseña debe tener al menos 6 caracteres.", "error")
            return redirect(url_for("recuperar_codigo"))
        if not validar_codigo(email, codigo, "reset"):
            flash("Código incorrecto o expirado.", "error")
            return redirect(url_for("recuperar_codigo"))

        r = Restaurante.query.filter_by(email=email).first()
        if r:
            r.set_password(pwd)
            db.session.commit()
        session.pop("reset_email", None)
        flash("Contraseña actualizada. Ya puedes iniciar sesión.", "success")
        return redirect(url_for("login"))

    return render_template("auth/recuperar_codigo.html", email=email)


# ══════════════════════════════════════════════
#  DASHBOARD
# ══════════════════════════════════════════════

@app.route("/dashboard")
@login_required
@plan_requerido
def dashboard():
    r               = restaurante_session()
    # Actualizar IP de red del restaurante en cada acceso al dashboard
    ip_actual = get_client_ip()
    if r.ip_red != ip_actual:
        r.ip_red = ip_actual
        db.session.commit()
    inicio, fin     = inicio_fin_dia_ec()

    ordenes_activas = Orden.query.filter(
        Orden.restaurante_id == r.id,
        Orden.estado.in_(["pendiente", "confirmada", "lista"]),
        Orden.fecha >= inicio,
        Orden.fecha <= fin,
    ).order_by(Orden.fecha.desc()).all()

    total_hoy = db.session.query(func.count(Orden.id)).filter(
        Orden.restaurante_id == r.id,
        Orden.estado == "pagada",
        Orden.fecha >= inicio,
        Orden.fecha <= fin,
    ).scalar() or 0

    ingresos_hoy = db.session.query(func.sum(Orden.total)).filter(
        Orden.restaurante_id == r.id,
        Orden.estado == "pagada",
        Orden.fecha >= inicio,
        Orden.fecha <= fin,
    ).scalar() or 0.0

    cuentas_solicitadas = sum(1 for o in ordenes_activas if o.solicita_cuenta)
    metodos_pago = MetodoPago.query.filter_by(
        restaurante_id=r.id, activo=True
    ).order_by(MetodoPago.orden_display).all()

    return render_template("restaurante/dashboard.html",
        restaurante=r,
        ordenes_activas=ordenes_activas,
        total_hoy=total_hoy,
        ingresos_hoy=ingresos_hoy,
        cuentas_solicitadas=cuentas_solicitadas,
        metodos_pago=metodos_pago,
        dias_plan=dias_plan(r),
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
        mesa = Mesa.query.get(o.mesa_id)
        if mesa:
            mesa.abierta = False
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
@plan_requerido
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


@app.route("/mesas/<int:mid>/qr")
@login_required
def imprimir_qr(mid):
    r    = restaurante_session()
    mesa = Mesa.query.filter_by(id=mid, restaurante_id=r.id).first_or_404()
    carta_url = request.host_url.rstrip("/") + f"/carta/{r.slug}/{mesa.token}"
    return render_template("restaurante/qr_imprimir.html",
        restaurante=r, mesa=mesa, carta_url=carta_url)


@app.route("/mesas/<int:mid>/toggle-sesion", methods=["POST"])
@login_required
def toggle_sesion_mesa(mid):
    r = restaurante_session()
    m = Mesa.query.filter_by(id=mid, restaurante_id=r.id).first_or_404()
    m.abierta = not m.abierta
    db.session.commit()
    estado = "abierta" if m.abierta else "cerrada"
    flash(f"{m.nombre} {estado}.", "success")
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

    # Verificar que el cliente esté en la misma red WiFi que el restaurante
    if r.restringir_red and r.ip_red and r.email != "demo@cartadigital.app":
        cliente_ip = get_client_ip()
        if cliente_ip != r.ip_red:
            return render_template("carta/red_requerida.html", restaurante=r)

    # Abrir la mesa solo si no hay pedido activo y el último pago fue hace más de 15 min.
    # Esto evita que el refresh del cliente reabre la mesa justo después del cobro.
    GRACIA = timedelta(minutes=15)
    orden_activa = Orden.query.filter(
        Orden.mesa_id == mesa.id,
        Orden.estado.in_(["pendiente", "confirmada", "lista"]),
    ).first()
    pago_reciente = Orden.query.filter(
        Orden.mesa_id == mesa.id,
        Orden.estado == "pagada",
        Orden.fecha_pago >= datetime.utcnow() - GRACIA,
    ).first()
    if not mesa.abierta and not orden_activa and not pago_reciente:
        mesa.abierta = True
        db.session.commit()

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
        mesa_abierta=mesa.abierta,
    )


@app.route("/carta/<slug>/<mesa_token>/agregar", methods=["POST"])
def carta_agregar(slug, mesa_token):
    r    = Restaurante.query.filter_by(slug=slug, activo=True).first_or_404()
    mesa = Mesa.query.filter_by(token=mesa_token, restaurante_id=r.id, activa=True).first_or_404()
    if not mesa.abierta:
        return redirect(url_for("carta", slug=slug, mesa_token=mesa_token))

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

    if not mesa.abierta:
        flash("Esta mesa no está disponible.", "error")
        return redirect(url_for("carta", slug=slug, mesa_token=mesa_token))

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
    metodos_pago = MetodoPago.query.filter_by(
        restaurante_id=orden.restaurante_id, activo=True
    ).order_by(MetodoPago.orden_display).all()
    return render_template("carta/orden.html", orden=orden,
                           restaurante=orden.restaurante, metodos_pago=metodos_pago)


@app.route("/orden/<token>/cuenta", methods=["POST"])
def solicitar_cuenta(token):
    orden = Orden.query.filter_by(token=token).first_or_404()
    if orden.estado == "lista":
        orden.solicita_cuenta  = True
        orden.metodo_preferido = request.form.get("metodo_preferido", "efectivo")
        db.session.commit()
    return redirect(url_for("estado_orden", token=token))


@app.route("/orden/<token>/recibo")
def recibo_orden(token):
    orden = Orden.query.filter_by(token=token).first_or_404()
    return render_template("carta/recibo.html", orden=orden, restaurante=orden.restaurante)


# ══════════════════════════════════════════════
#  REPORTES
# ══════════════════════════════════════════════

@app.route("/reportes")
@login_required
@plan_requerido
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
        ec_fecha = o.fecha + EC_OFFSET
        for item in o.items:
            w.writerow([
                ec_fecha.strftime("%d/%m/%Y"),
                ec_fecha.strftime("%H:%M"),
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
@plan_requerido
def perfil():
    r = restaurante_session()
    if request.method == "POST":
        r.nombre        = request.form.get("nombre", r.nombre).strip()
        r.whatsapp      = request.form.get("whatsapp", "").strip()
        r.ciudad        = request.form.get("ciudad", "").strip()
        r.descripcion   = request.form.get("descripcion", "").strip()
        r.restringir_red = "restringir_red" in request.form

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

    return render_template("restaurante/perfil.html", restaurante=r, ip_actual=get_client_ip())


@app.route("/perfil/actualizar-ip", methods=["POST"])
@login_required
def actualizar_ip_red():
    r = restaurante_session()
    r.ip_red = get_client_ip()
    db.session.commit()
    flash(f"IP de red actualizada a {r.ip_red}. Los clientes en este WiFi podrán ver el menú.", "success")
    return redirect(url_for("perfil"))


DEMO_EMAIL = "demo@cartadigital.app"
DEMO_PASS  = "demo1234"

DEMO_PRODUCTOS = [
    ("Ceviche de camarón",   "Camarones frescos marinados en limón, cebolla morada, cilantro y ají. Servido con chifles y patacones.",  7.50, "Entradas",  "https://picsum.photos/seed/ceviche1/900/700"),
    ("Patacones con hogao",  "Patacones crocantes acompañados de hogao casero y queso costeño.",                                        4.50, "Entradas",  "https://picsum.photos/seed/patacon2/900/700"),
    ("Seco de pollo",        "Pollo en salsa criolla de cerveza y especias, servido con arroz, menestra y aguacate.",                    8.50, "Principal", "https://picsum.photos/seed/chicken3/900/700"),
    ("Bandeja paisa",        "Frijoles, chicharrón, chorizo, huevo frito, arroz, aguacate, maduro y arepa. El plato más completo.",     10.00, "Principal", "https://picsum.photos/seed/bandeja4/900/700"),
    ("Arroz con mariscos",   "Arroz marinero con camarones, calamar y mejillones en salsa de tomate y azafrán.",                        12.00, "Principal", "https://picsum.photos/seed/seafood5/900/700"),
    ("Churrasco a la parrilla","350g de res a la parrilla con chimichurri casero, papas fritas y ensalada fresca.",                    14.00, "Principal", "https://picsum.photos/seed/steak6/900/700"),
    ("Sopa de quinua",       "Sopa andina con quinua, papa, zanahoria, apio y hierbas aromáticas. Reconfortante y nutritiva.",          5.50, "Sopas",     "https://picsum.photos/seed/soup7/900/700"),
    ("Caldo de gallina",     "Caldo tradicional de gallina criolla con papa, yuca, hierbas y ají.",                                     5.00, "Sopas",     "https://picsum.photos/seed/broth8/900/700"),
    ("Tres leches",          "Bizcocho bañado en tres tipos de leche, cubierto con crema chantilly y canela.",                          4.00, "Postres",   "https://picsum.photos/seed/cake9/900/700"),
    ("Flan de coco",         "Flan artesanal de coco con caramelo natural. Cremoso y ligero.",                                          3.50, "Postres",   "https://picsum.photos/seed/flan10/900/700"),
    ("Jugo de naranja",      "Naranja recién exprimida, 100% natural. Sin azúcar añadida.",                                             2.50, "Bebidas",   "https://picsum.photos/seed/juice11/900/700"),
    ("Cola de avena",        "Bebida tradicional de avena con leche, canela y azúcar. Fría y refrescante.",                             2.00, "Bebidas",   "https://picsum.photos/seed/oat12/900/700"),
    ("Cerveza artesanal",    "Cerveza artesanal local tipo lager. Fría y refrescante.",                                                  3.50, "Bebidas",   "https://picsum.photos/seed/beer13/900/700"),
]


def crear_demo():
    r = Restaurante.query.filter_by(email=DEMO_EMAIL).first()
    if not r:
        slug = "restaurante-demo"
        r = Restaurante(
            nombre="El Rincón Criollo",
            email=DEMO_EMAIL,
            slug=slug,
            whatsapp="0991234567",
            ciudad="Quito",
            descripcion="Cocina criolla ecuatoriana · Lun–Dom 8:00–22:00",
            logo_url="https://picsum.photos/seed/logorest/200/200",
        )
        r.set_password(DEMO_PASS)
        r.plan       = 'anual'
        r.plan_vence = datetime(2099, 12, 31)
        db.session.add(r)
        db.session.flush()

        for i in range(1, 9):
            db.session.add(Mesa(restaurante_id=r.id, numero=i,
                                nombre=f"Mesa {i}", token=Mesa.nuevo_token()))

        for i, (nombre, desc, precio, cat, img) in enumerate(DEMO_PRODUCTOS):
            db.session.add(Producto(
                restaurante_id=r.id, nombre=nombre, descripcion=desc,
                precio=precio, categoria=cat, imagen_url=img,
                disponible=True, orden_display=i,
            ))
        db.session.commit()
    return r


@app.route("/demo")
def demo_landing():
    r    = crear_demo()
    mesa = Mesa.query.filter_by(restaurante_id=r.id, numero=1).first()
    carta_url = url_for("carta", slug=r.slug, mesa_token=mesa.token, _external=False)
    return render_template("demo.html", restaurante=r, carta_url=carta_url)


@app.route("/demo/admin")
def demo_admin():
    r = crear_demo()
    session["restaurante_id"] = r.id
    flash("Estás en el panel de demostración — explora libremente.", "info")
    return redirect(url_for("dashboard"))


@app.route("/demo/prueba")
def demo_prueba():
    r    = crear_demo()
    session["restaurante_id"] = r.id          # auto-login como demo admin
    mesa = Mesa.query.filter_by(restaurante_id=r.id, numero=1).first()
    carta_url    = url_for("carta",     slug=r.slug, mesa_token=mesa.token)
    dashboard_url = url_for("dashboard")
    return render_template("demo_prueba.html",
        restaurante=r, carta_url=carta_url, dashboard_url=dashboard_url)


@app.route("/api/ordenes-activas")
@login_required
def api_ordenes_activas():
    from flask import jsonify
    r = restaurante_session()
    count = Orden.query.filter(
        Orden.restaurante_id == r.id,
        Orden.estado.in_(["pendiente", "confirmada", "lista"])
    ).count()
    pendientes = Orden.query.filter(
        Orden.restaurante_id == r.id,
        Orden.estado == "pendiente"
    ).count()
    cuentas = Orden.query.filter(
        Orden.restaurante_id == r.id,
        Orden.estado == "lista",
        Orden.solicita_cuenta == True,
    ).count()
    return jsonify({"count": count, "pendientes": pendientes, "cuentas": cuentas})


# ══════════════════════════════════════════════
#  MÉTODOS DE PAGO
# ══════════════════════════════════════════════

@app.route("/metodos-pago")
@login_required
def metodos_pago():
    r = restaurante_session()
    metodos = MetodoPago.query.filter_by(restaurante_id=r.id).order_by(MetodoPago.orden_display).all()
    return render_template("restaurante/metodos_pago.html", restaurante=r, metodos=metodos)


@app.route("/metodos-pago/agregar", methods=["POST"])
@login_required
def agregar_metodo_pago():
    r      = restaurante_session()
    nombre = request.form.get("nombre", "").strip()
    icono  = request.form.get("icono",  "💳").strip() or "💳"
    if nombre:
        ultimo = db.session.query(func.max(MetodoPago.orden_display)).filter_by(restaurante_id=r.id).scalar() or 0
        db.session.add(MetodoPago(restaurante_id=r.id, nombre=nombre, icono=icono, orden_display=ultimo+1))
        db.session.commit()
        flash(f"Método '{nombre}' agregado.", "success")
    return redirect(url_for("metodos_pago"))


@app.route("/metodos-pago/<int:mid>/toggle", methods=["POST"])
@login_required
def toggle_metodo_pago(mid):
    r = restaurante_session()
    m = MetodoPago.query.filter_by(id=mid, restaurante_id=r.id).first_or_404()
    m.activo = not m.activo
    db.session.commit()
    return redirect(url_for("metodos_pago"))


@app.route("/metodos-pago/<int:mid>/eliminar", methods=["POST"])
@login_required
def eliminar_metodo_pago(mid):
    r = restaurante_session()
    m = MetodoPago.query.filter_by(id=mid, restaurante_id=r.id).first_or_404()
    db.session.delete(m)
    db.session.commit()
    flash("Método eliminado.", "success")
    return redirect(url_for("metodos_pago"))


# ══════════════════════════════════════════════
#  SOPORTE
# ══════════════════════════════════════════════

@app.route("/soporte/enviar", methods=["POST"])
def soporte_enviar():
    from flask import jsonify
    nombre  = request.form.get("nombre",  "").strip()
    email   = request.form.get("email",   "").strip()
    mensaje = request.form.get("mensaje", "").strip()
    if not mensaje:
        return jsonify({"ok": False, "error": "El mensaje no puede estar vacío"}), 400
    db.session.add(MensajeSoporte(nombre=nombre, email=email, mensaje=mensaje))
    db.session.commit()
    return jsonify({"ok": True})


# ══════════════════════════════════════════════
#  SUPER-ADMIN
# ══════════════════════════════════════════════

ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASSWORD", "")


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        if (request.form.get("usuario") == ADMIN_USER and
                request.form.get("password") == ADMIN_PASS):
            session["is_admin"] = True
            return redirect(url_for("admin_panel"))
        return render_template("admin/login.html", error="Credenciales incorrectas")
    return render_template("admin/login.html", error=None)


@app.route("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    return redirect(url_for("admin_login"))


@app.route("/admin")
@admin_required
def admin_panel():
    restaurantes  = Restaurante.query.order_by(Restaurante.fecha_registro.desc()).all()
    msgs_no_leidos = MensajeSoporte.query.filter_by(leido=False).count()

    stats = {}
    for r in restaurantes:
        total_ordenes  = Orden.query.filter_by(restaurante_id=r.id).count()
        ordenes_hoy    = Orden.query.filter(
            Orden.restaurante_id == r.id,
            func.date(Orden.fecha) == date.today(),
        ).count()
        ingresos_total = db.session.query(func.sum(Orden.total)).filter(
            Orden.restaurante_id == r.id,
            Orden.estado == "pagada",
        ).scalar() or 0.0
        stats[r.id] = {
            "total_ordenes":  total_ordenes,
            "ordenes_hoy":    ordenes_hoy,
            "ingresos_total": ingresos_total,
        }

    return render_template("admin/panel.html", restaurantes=restaurantes, stats=stats,
                           msgs_no_leidos=msgs_no_leidos)


@app.route("/admin/restaurante/<int:rid>/panel")
@admin_required
def admin_ver_panel(rid):
    r = Restaurante.query.get_or_404(rid)
    session["restaurante_id"] = r.id   # impersona al restaurante
    return redirect(url_for("dashboard"))


@app.route("/admin/restaurante/<int:rid>/verificar", methods=["POST"])
@admin_required
def admin_verificar_email(rid):
    r = Restaurante.query.get_or_404(rid)
    r.email_verificado = True
    db.session.commit()
    flash(f"Email de {r.nombre} verificado manualmente.", "success")
    return redirect(url_for("admin_panel"))


@app.route("/admin/restaurante/<int:rid>/toggle", methods=["POST"])
@admin_required
def admin_toggle_restaurante(rid):
    r = Restaurante.query.get_or_404(rid)
    r.activo = not r.activo
    db.session.commit()
    return redirect(url_for("admin_panel"))


@app.route("/admin/restaurante/<int:rid>/eliminar", methods=["POST"])
@admin_required
def admin_eliminar_restaurante(rid):
    r = Restaurante.query.get_or_404(rid)
    db.session.delete(r)
    db.session.commit()
    return redirect(url_for("admin_panel"))


@app.route("/admin/mensajes")
@admin_required
def admin_mensajes():
    mensajes = MensajeSoporte.query.order_by(MensajeSoporte.fecha.desc()).all()
    # marcar todos como leídos al abrir la página
    MensajeSoporte.query.filter_by(leido=False).update({"leido": True})
    db.session.commit()
    return render_template("admin/mensajes.html", mensajes=mensajes)


@app.route("/admin/mensajes/<int:mid>/eliminar", methods=["POST"])
@admin_required
def admin_eliminar_mensaje(mid):
    m = MensajeSoporte.query.get_or_404(mid)
    db.session.delete(m)
    db.session.commit()
    return redirect(url_for("admin_mensajes"))


@app.route("/admin/restaurante/<int:rid>/plan", methods=["POST"])
@admin_required
def admin_set_plan(rid):
    r         = Restaurante.query.get_or_404(rid)
    plan_tipo = request.form.get("plan", "")
    fecha_str = request.form.get("fecha_inicio", "").strip()

    if plan_tipo not in PLANES and plan_tipo != "trial":
        flash("Plan inválido.", "error")
        return redirect(url_for("admin_panel"))

    try:
        fecha_inicio = datetime.strptime(fecha_str, "%Y-%m-%d") if fecha_str else datetime.utcnow()
    except ValueError:
        fecha_inicio = datetime.utcnow()

    r.plan        = plan_tipo
    r.plan_inicio = fecha_inicio
    if plan_tipo == "trial":
        r.plan_vence = fecha_inicio + timedelta(days=TRIAL_DIAS)
    else:
        r.plan_vence = fecha_inicio + timedelta(days=PLANES[plan_tipo]["dias"])
    db.session.commit()

    vence_str = r.plan_vence.strftime("%d/%m/%Y") if r.plan_vence else "—"
    flash(f"Plan '{r.plan}' asignado a {r.nombre}. Vence: {vence_str}", "success")
    return redirect(url_for("admin_panel"))


# ══════════════════════════════════════════════
#  PLANES (pública)
# ══════════════════════════════════════════════

@app.route("/planes")
def planes_page():
    return render_template("planes.html", planes=PLANES)


if __name__ == "__main__":
    app.run(debug=True, port=5001)
