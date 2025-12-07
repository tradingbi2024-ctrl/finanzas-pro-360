# finance.py
from __future__ import annotations

from datetime import date, datetime, timedelta
import calendar
import random

from flask import (
    Blueprint,
    render_template,
    jsonify,
    request,
    g,
    redirect,
    url_for,
)
from db import db
from models import User, Category, Income, SavingGoal, SavingDeposit

finance_bp = Blueprint("finance", __name__)

# ----------------------------------------------------------------------
#  VERSÍCULOS BÍBLICOS FINANCIEROS
# ----------------------------------------------------------------------
BIBLE_VERSES = [
    {
        "text": "Los planes del diligente ciertamente tienden a la abundancia.",
        "ref": "Proverbios 21:5",
    },
    {
        "text": "Honra al Señor con tus bienes y con las primicias de todos tus frutos.",
        "ref": "Proverbios 3:9",
    },
    {
        "text": "El alma del perezoso desea, y nada alcanza; mas el alma de los diligentes será prosperada.",
        "ref": "Proverbios 13:4",
    },
    {
        "text": "Buscad primero el reino de Dios y su justicia, y todas estas cosas os serán añadidas.",
        "ref": "Mateo 6:33",
    },
    {
        "text": "Todo lo que hagáis, hacedlo de corazón, como para el Señor y no para los hombres.",
        "ref": "Colosenses 3:23",
    },
]


def get_random_verse() -> dict:
    return random.choice(BIBLE_VERSES)


# ----------------------------------------------------------------------
#  HELPERS DE CÁLCULO FINANCIERO
# ----------------------------------------------------------------------
def get_user_working_days(user: User) -> int:
    """
    Días de trabajo configurados por el usuario.
    Si el modelo no tiene ese campo, usamos 26 por defecto.
    Rango forzado: 22–30.
    """
    days = getattr(user, "working_days", None)
    if not days:
        return 26
    try:
        value = int(days)
    except (TypeError, ValueError):
        value = 26
    return max(22, min(30, value))


def compute_financial_state(user: User, today: date | None = None) -> dict:
    """
    Cálculo principal del estado financiero del usuario para el mes actual.
    Devuelve todo lo necesario para:
      - Resumen del mes
      - Mensaje tipo coach
      - Mensaje del día
      - Estado de categorías
      - Estado de metas de ahorro
      - Versículo del día
    """
    if today is None:
        today = date.today()

    year = today.year
    month = today.month
    working_days = get_user_working_days(user)

    # Rango del mes
    first_day = date(year, month, 1)
    last_day = date(year, month, calendar.monthrange(year, month)[1])

    # Días transcurridos
    days_passed = (today - first_day).days + 1
    if days_passed < 1:
        days_passed = 1

    # ------------------ CATEGORÍAS / METAS ------------------
    categories = Category.query.filter_by(user_id=user.id).all()
    month_target = float(
        sum(float(c.monthly_target or 0) for c in categories)
    )
    if month_target <= 0:
        month_target = 1.0  # evitamos división por cero

    daily_target = month_target / working_days

    # ------------------ INGRESOS DEL MES ------------------
    incomes_q = Income.query.filter(
        Income.user_id == user.id,
        Income.date >= first_day,
        Income.date <= last_day,
    )
    incomes = incomes_q.all()
    month_income_real = float(sum(float(i.amount or 0) for i in incomes))

    todays_income = float(
        sum(float(i.amount or 0) for i in incomes if i.date == today)
    )

    effective_days_for_target = min(days_passed, working_days)
    ideal_income_until_today = daily_target * effective_days_for_target

    avg_daily_real = month_income_real / max(1, days_passed)
    projected_month_income = avg_daily_real * working_days
    projected_year_income = projected_month_income * 12

    ratio_month = month_income_real / month_target
    ratio_today = todays_income / daily_target if daily_target > 0 else 0
    ratio_until_today = (
        month_income_real / ideal_income_until_today
        if ideal_income_until_today > 0
        else 0
    )

    # ------------------ ESTADO DEL MES (COACH) ------------------
    if ratio_until_today < 0.5:
        month_status = "riesgo_alto"
        month_message = (
            "Estás muy por debajo de tu meta mensual. "
            "Revisa gastos, busca una actividad extra y refuerza tus ingresos "
            "esta semana."
        )
    elif ratio_until_today < 0.8:
        month_status = "riesgo_medio"
        month_message = (
            "Vas por debajo del ritmo ideal, pero aún tienes tiempo. "
            "Aprieta un poco más estos días y protege tus gastos."
        )
    elif ratio_until_today <= 1.1:
        month_status = "alineado"
        month_message = (
            "Vas bastante alineado con tu plan. Mantén la disciplina, "
            "no te confíes y sigue registrando cada día."
        )
    else:
        month_status = "excelente"
        month_message = (
            "¡Vas por encima de tu meta! Es un buen momento para fortalecer "
            "tu ahorro y crear un pequeño colchón extra."
        )

    # ------------------ ESTADO DEL DÍA ------------------
    if todays_income == 0:
        day_status = "sin_registro"
        day_message = (
            "Hoy aún no has registrado ingresos. "
            "La claridad diaria es clave para crecer."
        )
    elif ratio_today < 0.7:
        falta = daily_target - todays_income
        day_status = "debajo"
        day_message = (
            f"Hoy ganaste $ {todays_income:,.0f} y tu meta diaria es "
            f"$ {daily_target:,.0f}. Te faltaron aprox. "
            f"$ {falta:,.0f} para cumplir el objetivo de hoy."
        )
    elif ratio_today <= 1.1:
        day_status = "cumplido"
        day_message = (
            f"Buen trabajo. Hoy ganaste $ {todays_income:,.0f}, "
            f"muy cerca o por encima de tu meta diaria de "
            f"$ {daily_target:,.0f}."
        )
    else:
        extra = todays_income - daily_target
        day_status = "superado"
        day_message = (
            f"¡Excelente! Superaste tu meta diaria por aprox. "
            f"$ {extra:,.0f}. Considera dirigir una parte de ese extra "
            "directamente a tu ahorro."
        )

    # ------------------ ESTADO DE CATEGORÍAS ------------------
    def category_state(cat: Category) -> dict:
        meta_cat = float(cat.monthly_target or 0)

        # Estimamos cuánto debería ir a esta categoría según el peso
        if month_target > 0:
            real_cat = month_income_real * (meta_cat / month_target)
        else:
            real_cat = 0.0

        if working_days > 0:
            ideal_cat_until_today = meta_cat * (
                effective_days_for_target / working_days
            )
            daily_suggested = meta_cat / working_days
        else:
            ideal_cat_until_today = meta_cat
            daily_suggested = 0.0

        ratio_cat = (
            real_cat / ideal_cat_until_today
            if ideal_cat_until_today > 0
            else 0
        )

        if ratio_cat < 0.4:
            estado = "Muy por debajo"
        elif ratio_cat < 0.8:
            estado = "Por debajo"
        elif ratio_cat <= 1.1:
            estado = "En línea"
        else:
            estado = "Por encima"

        pct = (real_cat / meta_cat * 100) if meta_cat > 0 else 0

        return {
            "id": cat.id,
            "name": cat.name,
            "meta_mes": meta_cat,
            "real_mes_estimado": real_cat,
            "porcentaje": pct,
            "estado": estado,
            "diario_sugerido": daily_suggested,
        }

    categories_state = [category_state(c) for c in categories]

    # ------------------ AHORRO ------------------
    goals = SavingGoal.query.filter_by(user_id=user.id).all()
    saving_state: list[dict] = []

    for goal in goals:
        deposits = SavingDeposit.query.filter_by(goal_id=goal.id).all()
        acumulado = float(sum(float(d.amount or 0) for d in deposits))
        meta = float(goal.target_amount or 0)
        porcentaje = (acumulado / meta * 100) if meta > 0 else 0

        if goal.deadline and isinstance(goal.deadline, date):
            dias_restantes = (goal.deadline - today).days
        else:
            dias_restantes = None

        if dias_restantes is not None and dias_restantes > 0:
            diario_ahorro = max(0, (meta - acumulado) / dias_restantes)
        else:
            diario_ahorro = 0.0

        if porcentaje >= 100:
            msg_meta = (
                "Meta cumplida. Puedes definir un nuevo objetivo de ahorro."
            )
        elif porcentaje >= 70:
            msg_meta = (
                "Vas muy cerca de tu meta de ahorro. Mantén el ritmo."
            )
        elif porcentaje >= 40:
            msg_meta = (
                "Vas a mitad de camino. Refuerza un poco tus aportes."
            )
        else:
            msg_meta = (
                "Estás muy lejos de tu meta. Considera aportes más grandes "
                "o ampliar el plazo."
            )

        saving_state.append(
            {
                "id": goal.id,
                "name": goal.name,
                "meta": meta,
                "acumulado": acumulado,
                "porcentaje": porcentaje,
                "dias_restantes": dias_restantes,
                "diario_sugerido": diario_ahorro,
                "mensaje": msg_meta,
            }
        )

    verse = get_random_verse()

    return {
        "summary": {
            "year": year,
            "month": month,
            "month_target": month_target,
            "working_days": working_days,
            "daily_target": daily_target,
            "month_income_real": month_income_real,
            "todays_income": todays_income,
            "avg_daily_real": avg_daily_real,
            "projected_month_income": projected_month_income,
            "projected_year_income": projected_year_income,
            "ratio_month": ratio_month,
            "ratio_until_today": ratio_until_today,
            "month_status": month_status,
            "month_message": month_message,
            "day_status": day_status,
            "day_message": day_message,
        },
        "categories": categories_state,
        "saving": saving_state,
        "verse": verse,
    }


# ----------------------------------------------------------------------
#  RUTAS
# ----------------------------------------------------------------------
@finance_bp.before_request
def require_login():
    """Si no hay usuario cargado en g.user, redirigimos a login."""
    # app.py ya se encarga de cargar g.user en before_request global
    if request.endpoint and request.endpoint.startswith("finance."):
        if not getattr(g, "user", None):
            return redirect(url_for("auth.login"))


@finance_bp.route("/dashboard")
def dashboard():
    state = compute_financial_state(g.user)
    return render_template(
        "dashboard.html",
        user=g.user,
        state=state,
    )


# ------------------ API: ESTADO FINANCIERO ------------------
@finance_bp.route("/api/state", methods=["GET"])
def api_state():
    if not g.user:
        return jsonify({"ok": False, "error": "No autenticado"}), 401

    state = compute_financial_state(g.user)
    return jsonify({"ok": True, **state})


# ------------------ API: CATEGORÍAS ------------------
@finance_bp.route("/api/category", methods=["POST"])
def api_create_category():
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    target = float(data.get("monthly_target") or 0)

    if not name or target <= 0:
        return jsonify({"ok": False, "error": "Datos inválidos"}), 400

    cat = Category(user_id=g.user.id, name=name, monthly_target=target)
    db.session.add(cat)
    db.session.commit()
    return jsonify({"ok": True, "id": cat.id})


@finance_bp.route("/api/category/<int:cat_id>", methods=["PUT"])
def api_update_category(cat_id: int):
    cat = Category.query.filter_by(id=cat_id, user_id=g.user.id).first()
    if not cat:
        return jsonify({"ok": False, "error": "No encontrado"}), 404

    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    target = data.get("monthly_target")

    if name:
        cat.name = name
    if target is not None:
        try:
            cat.monthly_target = float(target)
        except ValueError:
            pass

    db.session.commit()
    return jsonify({"ok": True})


@finance_bp.route("/api/category/<int:cat_id>", methods=["DELETE"])
def api_delete_category(cat_id: int):
    cat = Category.query.filter_by(id=cat_id, user_id=g.user.id).first()
    if not cat:
        return jsonify({"ok": False, "error": "No encontrado"}), 404

    db.session.delete(cat)
    db.session.commit()
    return jsonify({"ok": True})


# ------------------ API: INGRESOS ------------------
@finance_bp.route("/api/income", methods=["POST"])
def api_add_income():
    data = request.get_json() or {}
    amount = float(data.get("amount") or 0)
    date_str = data.get("date") or ""
    try:
        income_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        income_date = date.today()

    if amount <= 0:
        return jsonify({"ok": False, "error": "Monto inválido"}), 400

    income = Income(user_id=g.user.id, amount=amount, date=income_date)
    db.session.add(income)
    db.session.commit()
    return jsonify({"ok": True})


# ------------------ API: METAS DE AHORRO ------------------
@finance_bp.route("/api/saving_goal", methods=["POST"])
def api_create_saving_goal():
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    target_amount = float(data.get("target_amount") or 0)
    deadline_str = data.get("deadline") or ""

    if not name or target_amount <= 0:
        return jsonify({"ok": False, "error": "Datos inválidos"}), 400

    if deadline_str:
        try:
            deadline = datetime.strptime(deadline_str, "%Y-%m-%d").date()
        except ValueError:
            deadline = None
    else:
        deadline = None

    goal = SavingGoal(
        user_id=g.user.id,
        name=name,
        target_amount=target_amount,
        deadline=deadline,
    )
    db.session.add(goal)
    db.session.commit()
    return jsonify({"ok": True, "id": goal.id})


@finance_bp.route("/api/saving_goal/<int:goal_id>", methods=["PUT"])
def api_update_saving_goal(goal_id: int):
    goal = SavingGoal.query.filter_by(id=goal_id, user_id=g.user.id).first()
    if not goal:
        return jsonify({"ok": False, "error": "No encontrado"}), 404

    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    target_amount = data.get("target_amount")
    deadline_str = data.get("deadline") or ""

    if name:
        goal.name = name
    if target_amount is not None:
        try:
            goal.target_amount = float(target_amount)
        except ValueError:
            pass
    if deadline_str:
        try:
            goal.deadline = datetime.strptime(
                deadline_str, "%Y-%m-%d"
            ).date()
        except ValueError:
            pass

    db.session.commit()
    return jsonify({"ok": True})


@finance_bp.route("/api/saving_goal/<int:goal_id>", methods=["DELETE"])
def api_delete_saving_goal(goal_id: int):
    goal = SavingGoal.query.filter_by(id=goal_id, user_id=g.user.id).first()
    if not goal:
        return jsonify({"ok": False, "error": "No encontrado"}), 404

    # Borramos también sus depósitos
    SavingDeposit.query.filter_by(goal_id=goal.id).delete()
    db.session.delete(goal)
    db.session.commit()
    return jsonify({"ok": True})


# ------------------ API: APORTES A METAS DE AHORRO ------------------
@finance_bp.route("/api/saving_deposit", methods=["POST"])
def api_create_saving_deposit():
    data = request.get_json() or {}
    goal_id = int(data.get("goal_id") or 0)
    amount = float(data.get("amount") or 0)
    date_str = data.get("date") or ""

    if amount <= 0 or not goal_id:
        return jsonify({"ok": False, "error": "Datos inválidos"}), 400

    goal = SavingGoal.query.filter_by(id=goal_id, user_id=g.user.id).first()
    if not goal:
        return jsonify({"ok": False, "error": "Meta no encontrada"}), 404

    try:
        deposit_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        deposit_date = date.today()

    deposit = SavingDeposit(
        goal_id=goal.id,
        amount=amount,
        date=deposit_date,
    )
    db.session.add(deposit)
    db.session.commit()
    return jsonify({"ok": True})
