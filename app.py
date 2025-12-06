from flask import (
    Flask,
    jsonify,
    request,
    render_template,
    make_response,
    session,
)
import json
import os
from datetime import date, datetime
from calendar import monthrange
from io import BytesIO

from werkzeug.security import generate_password_hash, check_password_hash

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = "CAMBIA_ESTA_CLAVE_SECRETA_POR_OTRA_MAS_LARGA"

DATA_FILE = "finanzas_data.json"


# ==========================
#   UTILIDADES BÁSICAS
# ==========================

def hoy():
    return date.today()


def anio_mes_actual():
    t = hoy()
    return t.year, t.month


def validar_password(p):
    """
    Reglas:
    - longitud exacta: 4
    - solo letras y números
    - al menos 1 letra
    - al menos 1 número
    """
    if not isinstance(p, str):
        return False
    if len(p) != 4:
        return False
    if not all(c.isalnum() for c in p):
        return False
    if not any(c.isalpha() for c in p):
        return False
    if not any(c.isdigit() for c in p):
        return False
    return True


def usuario_vacio(id_, nombre, email, password_hash):
    anio, mes = anio_mes_actual()
    return {
        "id": id_,
        "nombre": nombre,
        "email": email,
        "password_hash": password_hash,
        "config": {
            "anio": anio,
            "mes": mes,
            "dias_trabajo": 26,
            "meta_anual_manual_ingreso": 0.0,
            "meta_anual_manual_ahorro": 0.0
        },
        "categorias": [],
        "ingresos": [],
        "ahorros_metas": [],
        "ahorros_aportes": []
    }


# ==========================
#   CARGA / GUARDADO
# ==========================

def cargar_datos():
    if not os.path.exists(DATA_FILE):
        data = {
            "setup_done": False,
            "admin": None,
            "usuarios": []
        }
        guardar_datos(data)
        return data

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {
            "setup_done": False,
            "admin": None,
            "usuarios": []
        }

    # Migraciones mínimas
    if "setup_done" not in data:
        data["setup_done"] = False
    if "admin" not in data:
        data["admin"] = None
    if "usuarios" not in data:
        data["usuarios"] = []

    return data


def guardar_datos(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def buscar_usuario_por_id(data, user_id):
    for u in data.get("usuarios", []):
        if u.get("id") == user_id:
            return u
    return None


def buscar_usuario_por_email(data, email):
    email = (email or "").strip().lower()
    for u in data.get("usuarios", []):
        if (u.get("email") or "").lower() == email:
            return u
    return None


def get_usuario_actual():
    data = cargar_datos()
    role = session.get("role")
    if role != "user":
        return data, None
    uid = session.get("user_id")
    if uid is None:
        return data, None
    u = buscar_usuario_por_id(data, uid)
    return data, u


def get_admin_actual():
    data = cargar_datos()
    role = session.get("role")
    if role != "admin":
        return data, None
    return data, data.get("admin")


# ==========================
#   LÓGICA FINANCIERA
# ==========================

def obtener_config_mes(usuario):
    cfg = usuario.get("config", {})
    anio = int(cfg.get("anio", anio_mes_actual()[0]))
    mes = int(cfg.get("mes", anio_mes_actual()[1]))
    dias_trabajo = int(cfg.get("dias_trabajo", 26))
    dias_trabajo = max(22, min(dias_trabajo, 30))
    return anio, mes, dias_trabajo


def calcular_meta_ingreso(usuario):
    categorias = usuario.get("categorias", [])
    anio, mes, dias_trabajo = obtener_config_mes(usuario)

    monto_fijo_mensual = sum(
        float(c.get("monto_mensual", 0.0) or 0.0)
        for c in categorias
        if c.get("tipo") == "mensual"
    )

    sum_pct = sum(
        float(c.get("porcentaje", 0.0) or 0.0)
        for c in categorias
        if c.get("tipo") == "porcentaje"
    ) / 100.0

    dias_mes_cal = monthrange(anio, mes)[1]

    if monto_fijo_mensual <= 0 and sum_pct <= 0:
        return {
            "anio": anio,
            "mes": mes,
            "dias_mes_calendario": dias_mes_cal,
            "dias_trabajo": dias_trabajo,
            "ingreso_mensual_meta": 0.0,
            "ingreso_diario_meta": 0.0,
            "monto_fijo_mensual": 0.0,
            "sum_pct": 0.0
        }

    if sum_pct >= 0.9:
        sum_pct = 0.9

    ingreso_mensual_meta = (
        monto_fijo_mensual / (1 - sum_pct) if (1 - sum_pct) > 0 else monto_fijo_mensual
    )
    ingreso_diario_meta = ingreso_mensual_meta / dias_trabajo if dias_trabajo > 0 else ingreso_mensual_meta

    return {
        "anio": anio,
        "mes": mes,
        "dias_mes_calendario": dias_mes_cal,
        "dias_trabajo": dias_trabajo,
        "ingreso_mensual_meta": ingreso_mensual_meta,
        "ingreso_diario_meta": ingreso_diario_meta,
        "monto_fijo_mensual": monto_fijo_mensual,
        "sum_pct": sum_pct
    }


def filtrar_ingresos_mes(usuario, anio, mes):
    ingresos = []
    for ing in usuario.get("ingresos", []):
        try:
            f = datetime.strptime(ing["fecha"], "%Y-%m-%d").date()
            if f.year == anio and f.month == mes:
                ingresos.append({"fecha": f, "monto": float(ing["monto"])})
        except Exception:
            continue
    ingresos.sort(key=lambda x: x["fecha"])
    return ingresos


def calcular_resumen_mensual(usuario):
    meta = calcular_meta_ingreso(usuario)
    anio = meta["anio"]
    mes = meta["mes"]
    dias_trabajo = meta["dias_trabajo"]
    ingreso_diario_meta = meta["ingreso_diario_meta"]
    ingreso_mensual_meta = meta["ingreso_mensual_meta"]

    ingresos_mes = filtrar_ingresos_mes(usuario, anio, mes)
    total_ingresos = sum(i["monto"] for i in ingresos_mes)

    hoy_d = hoy()
    if hoy_d.year == anio and hoy_d.month == mes:
        ingreso_hoy = sum(i["monto"] for i in ingresos_mes if i["fecha"] == hoy_d)
        dia_actual = min(hoy_d.day, dias_trabajo)
    else:
        ingreso_hoy = 0.0
        dia_actual = dias_trabajo

    esperado_a_hoy = ingreso_diario_meta * dia_actual
    prom_diario_real = total_ingresos / max(1, dia_actual)

    if ingreso_mensual_meta <= 0:
        estado = "Sin presupuesto configurado."
        nivel = "neutral"
    else:
        ratio = total_ingresos / ingreso_mensual_meta
        if ratio < 0.7:
            estado = "🚨 Vida financiera en riesgo: muy por debajo de tu nivel necesario."
            nivel = "riesgo"
        elif ratio < 1.0:
            estado = "⚠️ Zona de incomodidad: vas por debajo del nivel financiero saludable."
            nivel = "ajustado"
        elif ratio < 1.3:
            estado = "🙂 Nivel de comodidad: estás cumpliendo la base de tu presupuesto."
            nivel = "comodidad"
        else:
            estado = "🟢 Zona de crecimiento: estás por encima del nivel básico, sigue así."
            nivel = "crecimiento"

    dias = list(range(1, dias_trabajo + 1))
    acumulado_plan = []
    acumulado_real = []

    acumulado = 0.0
    idx = 0
    for d in dias:
        acumulado_plan.append(ingreso_diario_meta * d)
        while idx < len(ingresos_mes) and ingresos_mes[idx]["fecha"].day == d:
            acumulado += ingresos_mes[idx]["monto"]
            idx += 1
        acumulado_real.append(acumulado)

    return {
        "meta": meta,
        "total_ingresos": total_ingresos,
        "prom_diario_real": prom_diario_real,
        "esperado_a_hoy": esperado_a_hoy,
        "ingreso_hoy": ingreso_hoy,
        "estado_texto": estado,
        "nivel": nivel,
        "serie": {
            "dias": dias,
            "plan_acumulado": acumulado_plan,
            "real_acumulado": acumulado_real
        }
    }


def calcular_resumen_categorias(usuario, resumen_mensual):
    categorias = usuario.get("categorias", [])
    ingreso_mensual_meta = resumen_mensual["meta"]["ingreso_mensual_meta"]

    anio = resumen_mensual["meta"]["anio"]
    mes = resumen_mensual["meta"]["mes"]
    ingresos_mes = filtrar_ingresos_mes(usuario, anio, mes)
    total_ingresos = sum(i["monto"] for i in ingresos_mes)

    resumen_cats = []
    for c in categorias:
        tipo = c.get("tipo")
        nombre = c.get("nombre")
        monto_mensual = float(c.get("monto_mensual", 0.0) or 0.0)
        porcentaje = float(c.get("porcentaje", 0.0) or 0.0)

        if tipo == "mensual":
            meta_mes = monto_mensual
            if ingreso_mensual_meta > 0 and total_ingresos > 0:
                factor = min(1.0, total_ingresos / ingreso_mensual_meta)
                real = meta_mes * factor
            else:
                real = 0.0
        else:
            meta_mes = ingreso_mensual_meta * (porcentaje / 100.0)
            real = total_ingresos * (porcentaje / 100.0)

        ratio = real / meta_mes if meta_mes > 0 else 0.0
        if ratio < 0.5:
            estado = "🔴 Muy por debajo"
        elif ratio < 0.9:
            estado = "🟡 Algo bajo"
        elif ratio < 1.1:
            estado = "🟢 Dentro de lo esperado"
        else:
            estado = "🟢 Por encima (bien)"

        resumen_cats.append({
            "id": c.get("id"),
            "nombre": nombre,
            "tipo": tipo,
            "monto_mensual": meta_mes,
            "porcentaje": porcentaje,
            "real_mes": real,
            "cumplimiento": ratio,
            "estado": estado
        })

    return resumen_cats


def calcular_resumen_ahorros(usuario):
    metas = usuario.get("ahorros_metas", [])
    aportes = usuario.get("ahorros_aportes", [])

    resumen = []
    for m in metas:
        meta_id = m.get("id")
        nombre = m.get("nombre")
        objetivo = float(m.get("objetivo", 0.0) or 0.0)
        fecha_inicio = datetime.strptime(m.get("fecha_inicio"), "%Y-%m-%d").date()
        fecha_fin = datetime.strptime(m.get("fecha_fin"), "%Y-%m-%d").date()

        total_aportado = sum(
            float(a.get("monto", 0.0) or 0.0)
            for a in aportes
            if a.get("meta_id") == meta_id
        )

        hoy_d = hoy()
        dias_totales = max(1, (fecha_fin - fecha_inicio).days + 1)
        dias_transcurridos = min(dias_totales, max(0, (hoy_d - fecha_inicio).days + 1))

        aporte_diario_necesario = objetivo / dias_totales
        meta_a_hoy = aporte_diario_necesario * dias_transcurridos

        if objetivo > 0:
            progreso_pct = min(1.0, total_aportado / objetivo)
        else:
            progreso_pct = 0.0

        if total_aportado >= meta_a_hoy:
            estado = "🟢 Vas bien con esta meta."
        else:
            estado = "⚠️ Vas por debajo, revisa tus aportes."

        if total_aportado == 0:
            sugerencia = "Considera una actividad secundaria para comenzar tus aportes: ventas pequeñas, oficios extra, etc."
        elif total_aportado < meta_a_hoy:
            sugerencia = "Estás por debajo del ahorro planeado. Revisa gastos, reduce fugas y busca cómo aumentar tus ingresos."
        else:
            sugerencia = "Excelente, mantén la disciplina y no toques este ahorro."

        resumen.append({
            "id": meta_id,
            "nombre": nombre,
            "objetivo": objetivo,
            "total_aportado": total_aportado,
            "progreso_pct": progreso_pct,
            "aporte_diario_necesario": aporte_diario_necesario,
            "meta_a_hoy": meta_a_hoy,
            "estado": estado,
            "sugerencia": sugerencia
        })

    return resumen


def calcular_distribucion_diaria(usuario, resumen_mensual):
    categorias = usuario.get("categorias", [])
    meta = resumen_mensual["meta"]
    ingreso_diario_meta = meta["ingreso_diario_meta"]
    ingreso_hoy = resumen_mensual.get("ingreso_hoy", 0.0)
    dias_trabajo = meta["dias_trabajo"]

    distrib = []
    total_ideal = 0.0
    total_real = 0.0

    for c in categorias:
        tipo = c.get("tipo")
        nombre = c.get("nombre")
        monto_mensual = float(c.get("monto_mensual", 0.0) or 0.0)
        porcentaje = float(c.get("porcentaje", 0.0) or 0.0)

        if tipo == "mensual":
            ideal_diario = monto_mensual / dias_trabajo if dias_trabajo > 0 else 0.0
            if ingreso_diario_meta > 0 and ingreso_hoy > 0:
                pct_ideal = ideal_diario / ingreso_diario_meta
                recomendado_hoy = pct_ideal * ingreso_hoy
            else:
                recomendado_hoy = 0.0
        else:
            ideal_diario = ingreso_diario_meta * (porcentaje / 100.0) if ingreso_diario_meta > 0 else 0.0
            recomendado_hoy = ingreso_hoy * (porcentaje / 100.0) if ingreso_hoy > 0 else 0.0

        total_ideal += ideal_diario
        total_real += recomendado_hoy

        distrib.append({
            "id": c.get("id"),
            "nombre": nombre,
            "tipo": tipo,
            "ideal_diario": ideal_diario,
            "recomendado_hoy": recomendado_hoy
        })

    disponible_ideal = ingreso_diario_meta - total_ideal
    disponible_real = ingreso_hoy - total_real

    if ingreso_diario_meta <= 0:
        mensaje = "Configura tus categorías y días de trabajo para calcular una meta diaria."
    elif ingreso_hoy <= 0:
        mensaje = "Aún no has registrado ingresos para hoy."
    else:
        ratio = ingreso_hoy / ingreso_diario_meta
        if ratio < 0.7:
            mensaje = "🚨 Ingreso de hoy muy por debajo de tu nivel ideal. Considera una actividad extra o revisar gastos."
        elif ratio < 1.0:
            mensaje = "⚠️ Ingreso de hoy algo por debajo del nivel ideal. Puedes compensar con un mejor día mañana."
        elif ratio < 1.4:
            mensaje = "🟢 Muy bien: cumpliste o superaste tu meta diaria de ingreso."
        else:
            mensaje = "🔥 Día excelente: superaste ampliamente tu meta diaria. Ideal para reforzar ahorro o inversión."

    return {
        "ingreso_real_hoy": ingreso_hoy,
        "ingreso_ideal_diario": ingreso_diario_meta,
        "total_ideal_categorias": total_ideal,
        "total_recomendado_hoy": total_real,
        "disponible_ideal": disponible_ideal,
        "disponible_real": disponible_real,
        "mensaje": mensaje,
        "distribucion": distrib
    }


def calcular_anual_ingresos(usuario):
    cfg = usuario.get("config", {})
    anio_actual = int(cfg.get("anio", anio_mes_actual()[0]))
    ingresos = usuario.get("ingresos", [])

    real_por_mes = {m: 0.0 for m in range(1, 13)}
    for ing in ingresos:
        try:
            f = datetime.strptime(ing["fecha"], "%Y-%m-%d").date()
            if f.year == anio_actual:
                real_por_mes[f.month] += float(ing["monto"])
        except Exception:
            continue

    meta = calcular_meta_ingreso(usuario)
    ingreso_mensual_meta = meta["ingreso_mensual_meta"]

    labels = []
    ideal = []
    reales = []
    for m in range(1, 13):
        labels.append(m)
        ideal.append(ingreso_mensual_meta)
        reales.append(real_por_mes[m])

    return {
        "anio": anio_actual,
        "meses": labels,
        "ideal_mensual": ideal,
        "real_mensual": reales,
        "meta_anual_auto": ingreso_mensual_meta * 12,
        "real_anual": sum(reales)
    }


# ==========================
#   VISTAS BÁSICAS
# ==========================

@app.route("/")
def index():
    return render_template("index.html")


# ==========================
#   AUTENTICACIÓN / ADMIN
# ==========================

@app.route("/api/auth/state", methods=["GET"])
def api_auth_state():
    data = cargar_datos()
    if not data.get("setup_done"):
        return jsonify({
            "setup_needed": True,
            "logged": False
        })

    role = session.get("role")
    if not role:
        return jsonify({
            "setup_needed": False,
            "logged": False
        })

    if role == "admin":
        admin = data.get("admin")
        return jsonify({
            "setup_needed": False,
            "logged": True,
            "role": "admin",
            "name": admin.get("nombre"),
            "email": admin.get("email")
        })

    if role == "user":
        uid = session.get("user_id")
        user = buscar_usuario_por_id(data, uid)
        if not user:
            session.clear()
            return jsonify({
                "setup_needed": False,
                "logged": False
            })
        return jsonify({
            "setup_needed": False,
            "logged": True,
            "role": "user",
            "name": user.get("nombre"),
            "email": user.get("email")
        })

    session.clear()
    return jsonify({
        "setup_needed": False,
        "logged": False
    })


@app.route("/api/auth/setup_admin", methods=["POST"])
def api_auth_setup_admin():
    data = cargar_datos()
    if data.get("setup_done"):
        return jsonify({"ok": False, "error": "El administrador ya está configurado."})

    body = request.get_json(force=True)
    nombre = (body.get("nombre") or "").strip()
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    confirm = body.get("confirm") or ""

    if not nombre or not email:
        return jsonify({"ok": False, "error": "Nombre y correo son obligatorios."})
    if password != confirm:
        return jsonify({"ok": False, "error": "Las contraseñas no coinciden."})
    if not validar_password(password):
        return jsonify({"ok": False, "error": "La contraseña debe tener 4 caracteres, con al menos una letra y un número."})

    phash = generate_password_hash(password)
    data["admin"] = {
        "nombre": nombre,
        "email": email,
        "password_hash": phash
    }
    data["setup_done"] = True
    guardar_datos(data)

    session.clear()
    session["role"] = "admin"
    return jsonify({"ok": True})


@app.route("/api/auth/admin/login", methods=["POST"])
def api_auth_admin_login():
    data = cargar_datos()
    if not data.get("setup_done") or not data.get("admin"):
        return jsonify({"ok": False, "error": "Administrador no configurado aún."})

    body = request.get_json(force=True)
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""

    admin = data.get("admin")
    if email != (admin.get("email") or "").lower():
        return jsonify({"ok": False, "error": "Credenciales inválidas."})

    if not check_password_hash(admin.get("password_hash", ""), password):
        return jsonify({"ok": False, "error": "Credenciales inválidas."})

    session.clear()
    session["role"] = "admin"
    return jsonify({"ok": True})


@app.route("/api/auth/user/register", methods=["POST"])
def api_auth_user_register():
    data = cargar_datos()
    if not data.get("setup_done"):
        return jsonify({"ok": False, "error": "Primero configura el administrador."})

    if len(data.get("usuarios", [])) >= 5:
        return jsonify({"ok": False, "error": "Máximo 5 perfiles de usuario."})

    body = request.get_json(force=True)
    nombre = (body.get("nombre") or "").strip()
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    confirm = body.get("confirm") or ""

    if not nombre or not email:
        return jsonify({"ok": False, "error": "Nombre y correo son obligatorios."})
    if password != confirm:
        return jsonify({"ok": False, "error": "Las contraseñas no coinciden."})
    if not validar_password(password):
        return jsonify({"ok": False, "error": "La contraseña debe tener 4 caracteres, con al menos una letra y un número."})

    if data.get("admin") and email == (data["admin"].get("email") or "").lower():
        return jsonify({"ok": False, "error": "Ese correo ya está usado por el administrador."})
    if buscar_usuario_por_email(data, email):
        return jsonify({"ok": False, "error": "Ya existe un usuario con ese correo."})

    existing_ids = [u.get("id", 0) for u in data.get("usuarios", [])]
    new_id = (max(existing_ids) + 1) if existing_ids else 1
    phash = generate_password_hash(password)

    nuevo = usuario_vacio(new_id, nombre, email, phash)
    data["usuarios"].append(nuevo)
    guardar_datos(data)

    session.clear()
    session["role"] = "user"
    session["user_id"] = new_id
    return jsonify({"ok": True})


@app.route("/api/auth/user/login", methods=["POST"])
def api_auth_user_login():
    data = cargar_datos()
    if not data.get("setup_done"):
        return jsonify({"ok": False, "error": "Primero configura el administrador."})

    body = request.get_json(force=True)
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""

    u = buscar_usuario_por_email(data, email)
    if not u:
        return jsonify({"ok": False, "error": "Credenciales inválidas."})

    if not check_password_hash(u.get("password_hash", ""), password):
        return jsonify({"ok": False, "error": "Credenciales inválidas."})

    session.clear()
    session["role"] = "user"
    session["user_id"] = u["id"]
    return jsonify({"ok": True})


@app.route("/api/auth/logout", methods=["POST"])
def api_auth_logout():
    session.clear()
    return jsonify({"ok": True})


# ==========================
#   ADMIN: GESTIÓN DE USUARIOS
# ==========================

@app.route("/api/admin/users", methods=["GET"])
def api_admin_users():
    data, admin = get_admin_actual()
    if admin is None:
        return jsonify({"ok": False, "error": "No autorizado."}), 403

    usuarios = [
        {"id": u["id"], "nombre": u["nombre"], "email": u["email"]}
        for u in data.get("usuarios", [])
    ]
    return jsonify({"ok": True, "usuarios": usuarios})


@app.route("/api/admin/users/delete", methods=["POST"])
def api_admin_delete_user():
    data, admin = get_admin_actual()
    if admin is None:
        return jsonify({"ok": False, "error": "No autorizado."}), 403

    body = request.get_json(force=True)
    try:
        uid = int(body.get("id"))
    except Exception:
        return jsonify({"ok": False, "error": "ID inválido."})

    usuarios = data.get("usuarios", [])
    nuevos = [u for u in usuarios if u.get("id") != uid]
    data["usuarios"] = nuevos
    guardar_datos(data)
    return jsonify({"ok": True})


@app.route("/api/user/delete", methods=["POST"])
def api_user_delete_self():
    data, usuario = get_usuario_actual()
    if usuario is None:
        return jsonify({"ok": False, "error": "No autorizado."}), 403

    uid = usuario["id"]
    usuarios = data.get("usuarios", [])
    nuevos = [u for u in usuarios if u.get("id") != uid]
    data["usuarios"] = nuevos
    guardar_datos(data)
    session.clear()
    return jsonify({"ok": True})


# ==========================
#   API DE DATOS DE USUARIO
# ==========================

@app.route("/api/state", methods=["GET"])
def api_state():
    data, usuario = get_usuario_actual()
    if usuario is None:
        return jsonify({"ok": False, "error": "No autorizado. Inicia sesión."}), 403

    resumen_mensual = calcular_resumen_mensual(usuario)
    resumen_cats = calcular_resumen_categorias(usuario, resumen_mensual)
    resumen_ahorro = calcular_resumen_ahorros(usuario)
    distrib_diaria = calcular_distribucion_diaria(usuario, resumen_mensual)
    anual = calcular_anual_ingresos(usuario)

    return jsonify({
        "ok": True,
        "perfil": {
            "id": usuario["id"],
            "nombre": usuario["nombre"],
            "email": usuario["email"],
            "config": usuario["config"]
        },
        "resumen_mensual": resumen_mensual,
        "categorias": resumen_cats,
        "ahorros": resumen_ahorro,
        "diario": distrib_diaria,
        "anual": anual
    })


@app.route("/api/profile/config_mes", methods=["POST"])
def api_profile_config_mes():
    data, usuario = get_usuario_actual()
    if usuario is None:
        return jsonify({"ok": False, "error": "No autorizado."}), 403

    body = request.get_json(force=True)
    try:
        anio = int(body.get("anio"))
        mes = int(body.get("mes"))
        dias_trabajo = int(body.get("dias_trabajo"))
    except Exception as e:
        return jsonify({"ok": False, "error": f"Datos inválidos: {e}"})

    dias_trabajo = max(22, min(dias_trabajo, 30))
    usuario["config"]["anio"] = anio
    usuario["config"]["mes"] = mes
    usuario["config"]["dias_trabajo"] = dias_trabajo

    meta_ing_anual = body.get("meta_anual_manual_ingreso")
    meta_ah_anual = body.get("meta_anual_manual_ahorro")
    if meta_ing_anual is not None:
        try:
            usuario["config"]["meta_anual_manual_ingreso"] = float(meta_ing_anual)
        except Exception:
            pass
    if meta_ah_anual is not None:
        try:
            usuario["config"]["meta_anual_manual_ahorro"] = float(meta_ah_anual)
        except Exception:
            pass

    guardar_datos(data)
    return jsonify({"ok": True})


# ---- Categorías ----

@app.route("/api/categoria", methods=["POST"])
def api_add_categoria():
    data, usuario = get_usuario_actual()
    if usuario is None:
        return jsonify({"ok": False, "error": "No autorizado."}), 403

    body = request.get_json(force=True)
    nombre = (body.get("nombre") or "").strip()
    tipo = body.get("tipo")
    valor = body.get("valor")

    if not nombre or tipo not in ("mensual", "porcentaje"):
        return jsonify({"ok": False, "error": "Datos de categoría inválidos."})

    try:
        valor = float(str(valor))
    except Exception:
        return jsonify({"ok": False, "error": "Valor numérico inválido."})

    existing_ids = [c.get("id", 0) for c in usuario.get("categorias", [])]
    new_id = (max(existing_ids) + 1) if existing_ids else 1

    if tipo == "mensual":
        cat = {
            "id": new_id,
            "nombre": nombre,
            "tipo": "mensual",
            "monto_mensual": valor,
            "porcentaje": 0.0
        }
    else:
        cat = {
            "id": new_id,
            "nombre": nombre,
            "tipo": "porcentaje",
            "monto_mensual": 0.0,
            "porcentaje": valor
        }

    usuario["categorias"].append(cat)
    guardar_datos(data)
    return jsonify({"ok": True})


@app.route("/api/categoria/update", methods=["POST"])
def api_update_categoria():
    data, usuario = get_usuario_actual()
    if usuario is None:
        return jsonify({"ok": False, "error": "No autorizado."}), 403

    body = request.get_json(force=True)
    try:
        cat_id = int(body.get("id"))
    except Exception:
        return jsonify({"ok": False, "error": "ID inválido."})

    nombre = (body.get("nombre") or "").strip()
    tipo = body.get("tipo")
    valor = body.get("valor")

    if not nombre or tipo not in ("mensual", "porcentaje"):
        return jsonify({"ok": False, "error": "Datos de categoría inválidos."})

    try:
        valor = float(str(valor))
    except Exception:
        return jsonify({"ok": False, "error": "Valor numérico inválido."})

    encontrada = False
    for c in usuario.get("categorias", []):
        if c.get("id") == cat_id:
            c["nombre"] = nombre
            c["tipo"] = tipo
            if tipo == "mensual":
                c["monto_mensual"] = valor
                c["porcentaje"] = 0.0
            else:
                c["monto_mensual"] = 0.0
                c["porcentaje"] = valor
            encontrada = True
            break

    if not encontrada:
        return jsonify({"ok": False, "error": "Categoría no encontrada."})

    guardar_datos(data)
    return jsonify({"ok": True})


@app.route("/api/categoria/delete", methods=["POST"])
def api_delete_categoria():
    data, usuario = get_usuario_actual()
    if usuario is None:
        return jsonify({"ok": False, "error": "No autorizado."}), 403

    body = request.get_json(force=True)
    try:
        cat_id = int(body.get("id"))
    except Exception:
        return jsonify({"ok": False, "error": "ID inválido."})

    cats = usuario.get("categorias", [])
    usuario["categorias"] = [c for c in cats if c.get("id") != cat_id]
    guardar_datos(data)
    return jsonify({"ok": True})


# ---- Ingresos ----

@app.route("/api/ingreso", methods=["POST"])
def api_add_ingreso():
    data, usuario = get_usuario_actual()
    if usuario is None:
        return jsonify({"ok": False, "error": "No autorizado."}), 403

    body = request.get_json(force=True)
    fecha_txt = body.get("fecha")
    monto = body.get("monto")

    try:
        f = datetime.strptime(fecha_txt, "%Y-%m-%d").date()
        monto = float(str(monto))
    except Exception as e:
        return jsonify({"ok": False, "error": f"Datos inválidos: {e}"})

    usuario["ingresos"].append({
        "fecha": f.strftime("%Y-%m-%d"),
        "monto": monto
    })
    guardar_datos(data)
    return jsonify({"ok": True})


# ---- Ahorro ----

@app.route("/api/ahorro/meta", methods=["POST"])
def api_add_meta_ahorro():
    data, usuario = get_usuario_actual()
    if usuario is None:
        return jsonify({"ok": False, "error": "No autorizado."}), 403

    if len(usuario.get("ahorros_metas", [])) >= 5:
        return jsonify({"ok": False, "error": "Ya tienes el máximo de 5 metas de ahorro."})

    body = request.get_json(force=True)
    nombre = (body.get("nombre") or "").strip()
    objetivo = body.get("objetivo")
    fecha_fin_txt = body.get("fecha_fin")

    if not nombre:
        return jsonify({"ok": False, "error": "Nombre de meta requerido."})

    try:
        objetivo = float(str(objetivo))
        fecha_inicio = hoy()
        fecha_fin = datetime.strptime(fecha_fin_txt, "%Y-%m-%d").date()
    except Exception as e:
        return jsonify({"ok": False, "error": f"Datos inválidos: {e}"})

    existing_ids = [m.get("id", 0) for m in usuario.get("ahorros_metas", [])]
    new_id = (max(existing_ids) + 1) if existing_ids else 1

    meta = {
        "id": new_id,
        "nombre": nombre,
        "objetivo": objetivo,
        "fecha_inicio": fecha_inicio.strftime("%Y-%m-%d"),
        "fecha_fin": fecha_fin.strftime("%Y-%m-%d")
    }
    usuario["ahorros_metas"].append(meta)
    guardar_datos(data)
    return jsonify({"ok": True})


@app.route("/api/ahorro/aporte", methods=["POST"])
def api_add_aporte_ahorro():
    data, usuario = get_usuario_actual()
    if usuario is None:
        return jsonify({"ok": False, "error": "No autorizado."}), 403

    body = request.get_json(force=True)
    meta_id = body.get("meta_id")
    fecha_txt = body.get("fecha")
    monto = body.get("monto")

    try:
        meta_id = int(meta_id)
        f = datetime.strptime(fecha_txt, "%Y-%m-%d").date()
        monto = float(str(monto))
    except Exception as e:
        return jsonify({"ok": False, "error": f"Datos inválidos: {e}"})

    metas_ids = [m.get("id") for m in usuario.get("ahorros_metas", [])]
    if meta_id not in metas_ids:
        return jsonify({"ok": False, "error": "Meta de ahorro no encontrada."})

    aportes = usuario.get("ahorros_aportes", [])
    existing_ids = [a.get("id", 0) for a in aportes]
    new_id = (max(existing_ids) + 1) if existing_ids else 1

    aportes.append({
        "id": new_id,
        "meta_id": meta_id,
        "fecha": f.strftime("%Y-%m-%d"),
        "monto": monto
    })
    usuario["ahorros_aportes"] = aportes
    guardar_datos(data)
    return jsonify({"ok": True})


@app.route("/api/ahorro/aporte/update", methods=["POST"])
def api_update_aporte_ahorro():
    data, usuario = get_usuario_actual()
    if usuario is None:
        return jsonify({"ok": False, "error": "No autorizado."}), 403

    body = request.get_json(force=True)
    try:
        aporte_id = int(body.get("id"))
    except Exception:
        return jsonify({"ok": False, "error": "ID inválido."})

    fecha_txt = body.get("fecha")
    monto = body.get("monto")

    try:
        f = datetime.strptime(fecha_txt, "%Y-%m-%d").date()
        monto = float(str(monto))
    except Exception as e:
        return jsonify({"ok": False, "error": f"Datos inválidos: {e}"})

    encontrada = False
    for a in usuario.get("ahorros_aportes", []):
        if a.get("id") == aporte_id:
            a["fecha"] = f.strftime("%Y-%m-%d")
            a["monto"] = monto
            encontrada = True
            break

    if not encontrada:
        return jsonify({"ok": False, "error": "Aporte no encontrado."})

    guardar_datos(data)
    return jsonify({"ok": True})


@app.route("/api/ahorro/aporte/delete", methods=["POST"])
def api_delete_aporte_ahorro():
    data, usuario = get_usuario_actual()
    if usuario is None:
        return jsonify({"ok": False, "error": "No autorizado."}), 403

    body = request.get_json(force=True)
    try:
        aporte_id = int(body.get("id"))
    except Exception:
        return jsonify({"ok": False, "error": "ID inválido."})

    aportes = usuario.get("ahorros_aportes", [])
    usuario["ahorros_aportes"] = [a for a in aportes if a.get("id") != aporte_id]
    guardar_datos(data)
    return jsonify({"ok": True})


# ---- PDF REPORTE ----

@app.route("/api/reporte/pdf", methods=["GET"])
def api_reporte_pdf():
    data, usuario = get_usuario_actual()
    if usuario is None:
        return jsonify({"ok": False, "error": "No autorizado."}), 403

    if not REPORTLAB_AVAILABLE:
        return jsonify({"ok": False, "error": "reportlab no instalado. Instala con: pip install reportlab"})

    resumen_mensual = calcular_resumen_mensual(usuario)
    resumen_cats = calcular_resumen_categorias(usuario, resumen_mensual)
    resumen_ahorro = calcular_resumen_ahorros(usuario)
    anual = calcular_anual_ingresos(usuario)

    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    y = height - 40
    p.setFont("Helvetica-Bold", 14)
    p.drawString(40, y, f"Informe financiero - Usuario: {usuario['nombre']}")
    y -= 20
    p.setFont("Helvetica", 10)
    meta = resumen_mensual["meta"]
    p.drawString(40, y, f"Mes: {meta['anio']}-{meta['mes']:02d}  |  Días de trabajo: {meta['dias_trabajo']}")
    y -= 15
    p.drawString(40, y, f"Meta ingreso mensual: {resumen_mensual['meta']['ingreso_mensual_meta']:.0f}")
    y -= 15
    p.drawString(40, y, f"Ingresos reales del mes: {resumen_mensual['total_ingresos']:.0f}")
    y -= 15
    p.drawString(40, y, f"Ingreso diario ideal: {meta['ingreso_diario_meta']:.0f}")
    y -= 15
    p.drawString(40, y, f"Ingreso diario promedio real: {resumen_mensual['prom_diario_real']:.0f}")
    y -= 25

    p.setFont("Helvetica-Bold", 12)
    p.drawString(40, y, "Categorías")
    y -= 15
    p.setFont("Helvetica", 9)
    for c in resumen_cats:
        linea = f"- {c['nombre']} | tipo: {c['tipo']} | meta mes: {c['monto_mensual']:.0f} | real: {c['real_mes']:.0f} | {c['estado']}"
        p.drawString(40, y, linea[:110])
        y -= 12
        if y < 80:
            p.showPage()
            y = height - 40
            p.setFont("Helvetica", 9)

    y -= 10
    p.setFont("Helvetica-Bold", 12)
    p.drawString(40, y, "Metas de ahorro")
    y -= 15
    p.setFont("Helvetica", 9)
    for a in resumen_ahorro:
        linea = f"- {a['nombre']} | objetivo: {a['objetivo']:.0f} | aportado: {a['total_aportado']:.0f} ({a['progreso_pct']*100:.0f}%)"
        p.drawString(40, y, linea[:110])
        y -= 12
        if y < 80:
            p.showPage()
            y = height - 40
            p.setFont("Helvetica", 9)

    y -= 10
    p.setFont("Helvetica-Bold", 12)
    p.drawString(40, y, "Proyección anual (ingresos)")
    y -= 15
    p.setFont("Helvetica", 9)
    p.drawString(40, y, f"Meta anual automática (x12): {anual['meta_anual_auto']:.0f}")
    y -= 12
    p.drawString(40, y, f"Ingreso anual real acumulado: {anual['real_anual']:.0f}")

    p.showPage()
    p.save()
    buffer.seek(0)

    response = make_response(buffer.read())
    response.headers.set("Content-Type", "application/pdf")
    response.headers.set("Content-Disposition", "attachment", filename="informe_financiero.pdf")
    return response


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)