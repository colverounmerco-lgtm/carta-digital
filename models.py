from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
import secrets
import re

db = SQLAlchemy()


def slugify(text):
    text = text.lower().strip()
    for a, b in [("á","a"),("à","a"),("ä","a"),("é","e"),("è","e"),("ë","e"),
                 ("í","i"),("ì","i"),("ï","i"),("ó","o"),("ò","o"),("ö","o"),
                 ("ú","u"),("ù","u"),("ü","u"),("ñ","n")]:
        text = text.replace(a, b)
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s-]+", "-", text)
    return text.strip("-")


class Restaurante(db.Model):
    __tablename__ = "restaurantes"
    id               = db.Column(db.Integer, primary_key=True)
    nombre           = db.Column(db.String(100), nullable=False)
    email            = db.Column(db.String(120), unique=True, nullable=False)
    password_hash    = db.Column(db.String(256), nullable=False)
    whatsapp         = db.Column(db.String(20))
    ciudad           = db.Column(db.String(80))
    logo_url         = db.Column(db.String(300))
    slug             = db.Column(db.String(100), unique=True, nullable=False)
    descripcion      = db.Column(db.Text)
    activo           = db.Column(db.Boolean, default=True)
    email_verificado = db.Column(db.Boolean, default=False)
    fecha_registro   = db.Column(db.DateTime, default=datetime.utcnow)
    plan             = db.Column(db.String(20), default='trial')  # trial | mensual | anual
    plan_inicio      = db.Column(db.DateTime)
    plan_vence       = db.Column(db.DateTime)
    ip_red           = db.Column(db.String(50))   # IP pública del restaurante
    restringir_red   = db.Column(db.Boolean, default=True)  # False = menú accesible desde cualquier red
    dia_apertura     = db.Column(db.Date)         # Último día en que se auto-abrieron las mesas
    modo_cobro       = db.Column(db.Boolean, default=False)  # True = cobro anticipado (mostrador)

    mesas    = db.relationship("Mesa",     backref="restaurante", lazy=True, cascade="all, delete-orphan")
    productos = db.relationship("Producto", backref="restaurante", lazy=True, cascade="all, delete-orphan")
    ordenes  = db.relationship("Orden",    backref="restaurante", lazy=True)

    def set_password(self, pwd):
        self.password_hash = generate_password_hash(pwd)

    def check_password(self, pwd):
        return check_password_hash(self.password_hash, pwd)


class Mesa(db.Model):
    __tablename__ = "mesas"
    id             = db.Column(db.Integer, primary_key=True)
    restaurante_id = db.Column(db.Integer, db.ForeignKey("restaurantes.id"), nullable=False)
    numero         = db.Column(db.Integer, nullable=False)
    nombre         = db.Column(db.String(50))
    token          = db.Column(db.String(40), unique=True, nullable=False)
    activa         = db.Column(db.Boolean, default=True)
    abierta        = db.Column(db.Boolean, default=False)  # False = bloqueada para pedidos; abre al escanear QR
    es_para_llevar = db.Column(db.Boolean, default=False)

    ordenes = db.relationship("Orden", backref="mesa", lazy=True)

    @staticmethod
    def nuevo_token():
        return secrets.token_urlsafe(20)


class Producto(db.Model):
    __tablename__ = "productos"
    id             = db.Column(db.Integer, primary_key=True)
    restaurante_id = db.Column(db.Integer, db.ForeignKey("restaurantes.id"), nullable=False)
    nombre         = db.Column(db.String(100), nullable=False)
    descripcion    = db.Column(db.Text)
    precio         = db.Column(db.Float, nullable=False)
    imagen_url     = db.Column(db.String(300))
    categoria      = db.Column(db.String(50), default="Principal")
    disponible     = db.Column(db.Boolean, default=True)
    orden_display  = db.Column(db.Integer, default=0)
    terminos_asado    = db.Column(db.Boolean, default=False)
    salsas_activas    = db.Column(db.Boolean, default=False)
    adiciones_activas = db.Column(db.Boolean, default=False)
    bebidas_activas   = db.Column(db.Boolean, default=False)
    sabores_activos   = db.Column(db.Boolean, default=False)

    items   = db.relationship("ItemOrden",    backref="producto",     lazy=True)
    sabores = db.relationship("SaborProducto", backref="producto_obj", lazy=True,
                              cascade="all, delete-orphan",
                              order_by="SaborProducto.orden_display")


class Orden(db.Model):
    __tablename__ = "ordenes"
    id              = db.Column(db.Integer, primary_key=True)
    restaurante_id  = db.Column(db.Integer, db.ForeignKey("restaurantes.id"), nullable=False)
    mesa_id         = db.Column(db.Integer, db.ForeignKey("mesas.id"), nullable=False)
    token           = db.Column(db.String(40), unique=True, nullable=False)
    nombre_cliente  = db.Column(db.String(100))
    estado          = db.Column(db.String(20), default="pendiente")
    # pendiente → confirmada → lista → pagada | cancelada
    total           = db.Column(db.Float, default=0.0)
    metodo_pago     = db.Column(db.String(30))
    notas           = db.Column(db.Text)
    solicita_cuenta  = db.Column(db.Boolean, default=False)
    metodo_preferido = db.Column(db.String(30))   # método elegido por el cliente
    fecha            = db.Column(db.DateTime, default=datetime.utcnow)
    fecha_pago       = db.Column(db.DateTime)

    items = db.relationship("ItemOrden", backref="orden", lazy=True, cascade="all, delete-orphan")

    @staticmethod
    def nuevo_token():
        return secrets.token_urlsafe(20)

    @property
    def estado_label(self):
        return {
            "pendiente":  "Nuevo pedido",
            "confirmada": "En preparación",
            "lista":      "Listo para entregar",
            "pagada":     "Pagado",
            "cancelada":  "Cancelado",
        }.get(self.estado, self.estado)

    @property
    def estado_paso(self):
        return {"pendiente": 1, "confirmada": 2, "lista": 3, "pagada": 4}.get(self.estado, 0)


class CodigoVerificacion(db.Model):
    __tablename__ = "codigos_verificacion"
    id     = db.Column(db.Integer, primary_key=True)
    email  = db.Column(db.String(120), nullable=False)
    codigo = db.Column(db.String(6), nullable=False)
    tipo   = db.Column(db.String(20), nullable=False)  # 'registro' | 'reset'
    expira = db.Column(db.DateTime, nullable=False)
    usado  = db.Column(db.Boolean, default=False)


class Salsa(db.Model):
    __tablename__ = "salsas"
    id             = db.Column(db.Integer, primary_key=True)
    restaurante_id = db.Column(db.Integer, db.ForeignKey("restaurantes.id"), nullable=False)
    nombre         = db.Column(db.String(80), nullable=False)
    activa         = db.Column(db.Boolean, default=True)
    orden_display  = db.Column(db.Integer, default=0)


class SeccionBebida(db.Model):
    __tablename__ = "secciones_bebida"
    id             = db.Column(db.Integer, primary_key=True)
    restaurante_id = db.Column(db.Integer, db.ForeignKey("restaurantes.id"), nullable=False)
    nombre         = db.Column(db.String(80), nullable=False)   # "Colas", "Jugos", "Batidos"
    activa         = db.Column(db.Boolean, default=True)
    orden_display  = db.Column(db.Integer, default=0)
    variantes      = db.relationship("VarianteBebida", backref="seccion", lazy=True,
                                     cascade="all, delete-orphan", order_by="VarianteBebida.orden_display")



class VarianteBebida(db.Model):
    __tablename__ = "variantes_bebida"
    id         = db.Column(db.Integer, primary_key=True)
    seccion_id = db.Column(db.Integer, db.ForeignKey("secciones_bebida.id"), nullable=False)
    nombre     = db.Column(db.String(80), nullable=False)       # "Coca-Cola", "Naranja", "Fresa"
    activa     = db.Column(db.Boolean, default=True)
    orden_display = db.Column(db.Integer, default=0)


class SaborProducto(db.Model):
    __tablename__ = "sabores_producto"
    id            = db.Column(db.Integer, primary_key=True)
    producto_id   = db.Column(db.Integer, db.ForeignKey("productos.id"), nullable=False)
    nombre        = db.Column(db.String(80), nullable=False)
    activo        = db.Column(db.Boolean, default=True)
    orden_display = db.Column(db.Integer, default=0)


class Adicion(db.Model):
    __tablename__ = "adiciones"
    id             = db.Column(db.Integer, primary_key=True)
    restaurante_id = db.Column(db.Integer, db.ForeignKey("restaurantes.id"), nullable=False)
    nombre         = db.Column(db.String(80), nullable=False)
    precio         = db.Column(db.Float, default=0.0)
    activa         = db.Column(db.Boolean, default=True)
    orden_display  = db.Column(db.Integer, default=0)


class MetodoPago(db.Model):
    __tablename__ = "metodos_pago"
    id             = db.Column(db.Integer, primary_key=True)
    restaurante_id = db.Column(db.Integer, db.ForeignKey("restaurantes.id"), nullable=False)
    nombre         = db.Column(db.String(50), nullable=False)
    icono          = db.Column(db.String(300), default="💳")
    activo         = db.Column(db.Boolean, default=True)
    orden_display  = db.Column(db.Integer, default=0)


class MensajeSoporte(db.Model):
    __tablename__ = "mensajes_soporte"
    id      = db.Column(db.Integer, primary_key=True)
    nombre  = db.Column(db.String(100))
    email   = db.Column(db.String(120))
    mensaje = db.Column(db.Text, nullable=False)
    leido   = db.Column(db.Boolean, default=False)
    fecha   = db.Column(db.DateTime, default=datetime.utcnow)


class ItemOrden(db.Model):
    __tablename__ = "items_orden"
    id              = db.Column(db.Integer, primary_key=True)
    orden_id        = db.Column(db.Integer, db.ForeignKey("ordenes.id"), nullable=False)
    producto_id     = db.Column(db.Integer, db.ForeignKey("productos.id"), nullable=False)
    cantidad        = db.Column(db.Integer, nullable=False)
    precio_unitario = db.Column(db.Float, nullable=False)
    subtotal        = db.Column(db.Float, nullable=False)
    notas_item      = db.Column(db.String(200))
