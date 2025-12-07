from datetime import date, datetime

from flask import (
    Blueprint,
    render_template,
    request,
    jsonify,
    g,
)

from db import db
from models import (
    User,
    DailyIncome,
    Category,
    CategoryContribution,
    SavingGoal,
    SavingContribution,
)
from auth import login_required

finance_bp = Blueprint("finance", __name__, url_prefix="")

# -------------------- helpers --------------------


def _month_range(year, month):
    from calendar import monthrange

    days = monthrange(year, month)[1]
    start = date(year, month, 1)
    end = date(year, month, days)
    return start, end, days


def _current_year_month():
    today = date.today()
    return today.year, today.month


def _sum_numeric(iterable):
    return float(sum(x for x in iterable or []))


def build_month_state(user: User, year: int, month: int):
    start, end, days_in_month = _month_range(year, month)
    today = date.today()
    day_of_month = min(days_in_month, today.day)

    # Ingresos del mes
    incomes_q = (
        DailyIncome.query.filter_by(user_id=user.id)
        .filter(DailyIncome.date >= start)
        .filter(DailyIncome.date <= end)
    )
    incomes_amounts = [float(i.amount) for i in incomes_q]
    total_income_month = _sum_numeric(incomes_amounts)

    # Meta mensual = suma de metas de categorías
    categories = Category.query.filter_by(user_id=user.id).all()
    monthly_income_goal = _sum_numeric([float(c.monthly_goal) for c in categories])

    working_days = max(22, min(30, user.working_days or 26))
    daily_income_goal = monthly_income_goal / working_days if working_days else 0

    real_daily_avg = total_income_month / day_of_month if day_of_month else 0

    # Diagnóstico general de ingresos
    if total_income_month == 0:
        income_status = "Aún no registras ingresos este mes."
    else:
        esperado_a_la_fecha = daily_income_goal * day_of_month
        if total_income_month < esperado_a_la_fecha * 0.7:
            income_status = "💣 Vida financiera en riesgo: vas muy por debajo de tu nivel necesario."
        elif total_income_month < esperado_a_la_fecha * 0.9:
            income_status = "⚠ Estás un poco por debajo de lo esperado. Ajusta gastos o busca ingresos extra."
        else:
            income_status = "✅ Buen ritmo: estás cumpliendo o superando tu meta de ingresos."

    # Categorías
    cat_states = []
    for c in categories:
        contrib_q = (
            CategoryContribution.query.filter_by(user_id=user.id, category_id=c.id)
            .filter(CategoryContribution.date >= start)
            .filter(CategoryContribution.date <= end)
        )
        aportes = [float(x.amount) for x in contrib_q]
        real_mes = _sum_numeric(aportes)
        meta_mes = float(c.monthly_goal)
        perc = (real_mes / meta_mes * 100) if meta_mes > 0 else 0

        if perc < 50:
            estado = "Muy por debajo"
        elif perc < 90:
            estado = "Algo por debajo"
        elif perc <= 110:
            estado = "En rango"
        else:
            estado = "Por encima (sobrecarga)"

        diario_sugerido = meta_mes / working_days if working_days else 0

        cat_states.append(
            {
                "id": c.id,
                "name": c.name,
                "meta_mes": meta_mes,
                "real_mes": real_mes,
                "perc": round(perc, 1) if meta_mes > 0 else 0,
                "estado": estado,
                "diario_sugerido": diario_sugerido,
            }
        )

    # Metas de ahorro
    goals = SavingGoal.query.filter_by(user_id=user.id).all()
    saving_states = []
    for ggoal in goals:
        contrib_q = SavingContribution.query.filter_by(goal_id=ggoal.id)
        aportes = [float(x.amount) for x in contrib_q]
        real = _sum_numeric(aportes)
        target = float(ggoal.target_amount)
        perc = (real / target * 100) if target > 0 else 0

        saving_states.append(
            {
                "id": ggoal.id,
                "name": ggoal.name,
                "target": target,
                "real": real,
                "perc": round(perc, 1) if target > 0 else 0,
                "deadline": ggoal.deadline.isoformat() if ggoal.deadline else "",
            }
        )

    # Proyección anual (simple: multiplicar mes actual * 12)
    projected_annual_income = total_income_month * 12

    return {
        "year": year,
        "month": month,
        "days_in_month": days_in_month,
        "day_of_month": day_of_month,
        "working_days": working_days,
        "monthly_income_goal": monthly_income_goal,
        "daily_income_goal": daily_income_goal,
        "total_income_month": total_income_month,
        "real_daily_avg": real_daily_avg,
        "income_status": income_status,
        "categories": cat_states,
        "saving_goals": saving_states,
        "projected_annual_income": projected_annual_income,
    }


# -------------------- vistas --------------------


@finance_bp.route("/dashboard")
@login_required
def dashboard():
    year, month = _current_year_month()
    state = build_month_state(g.user, year, month)
    return render_template("dashboard.html", state=state, user=g.user)


@finance_bp.route("/api/state")
@login_required
def api_state():
    year, month = _current_year_month()
    state = build_month_state(g.user, year, month)
    return jsonify({"ok": True, "state": state})


@finance_bp.route("/api/category", methods=["POST"])
@login_required
def api_category():
    data = request.get_json() or {}
    action = data.get("action", "create")
    name = (data.get("name") or "").strip()
    monthly_goal = float(data.get("monthly_goal") or 0)
    cat_id = data.get("id")

    if action == "create":
        if not name or monthly_goal <= 0:
            return jsonify({"ok": False, "error": "Nombre y meta mensual son obligatorios."})
        c = Category(user_id=g.user.id, name=name, monthly_goal=monthly_goal)
        db.session.add(c)
        db.session.commit()
    elif action == "update":
        c = Category.query.filter_by(id=cat_id, user_id=g.user.id).first()
        if not c:
            return jsonify({"ok": False, "error": "Categoría no encontrada."})
        if name:
            c.name = name
        if monthly_goal > 0:
            c.monthly_goal = monthly_goal
        db.session.commit()
    elif action == "delete":
        c = Category.query.filter_by(id=cat_id, user_id=g.user.id).first()
        if not c:
            return jsonify({"ok": False, "error": "Categoría no encontrada."})
        db.session.delete(c)
        db.session.commit()
    else:
        return jsonify({"ok": False, "error": "Acción no válida."})

    year, month = _current_year_month()
    state = build_month_state(g.user, year, month)
    return jsonify({"ok": True, "state": state})


@finance_bp.route("/api/income", methods=["POST"])
@login_required
def api_income():
    data = request.get_json() or {}
    date_txt = data.get("date")
    amount = float(data.get("amount") or 0)

    try:
        d = datetime.strptime(date_txt, "%Y-%m-%d").date()
    except Exception:
        d = date.today()

    if amount <= 0:
        return jsonify({"ok": False, "error": "El monto debe ser mayor a cero."})

    inc = DailyIncome(user_id=g.user.id, date=d, amount=amount)
    db.session.add(inc)
    db.session.commit()

    year, month = _current_year_month()
    state = build_month_state(g.user, year, month)
    return jsonify({"ok": True, "state": state})


@finance_bp.route("/api/category_contribution", methods=["POST"])
@login_required
def api_category_contribution():
    data = request.get_json() or {}
    cat_id = data.get("category_id")
    amount = float(data.get("amount") or 0)
    date_txt = data.get("date")

    try:
        d = datetime.strptime(date_txt, "%Y-%m-%d").date()
    except Exception:
        d = date.today()

    c = Category.query.filter_by(id=cat_id, user_id=g.user.id).first()
    if not c:
        return jsonify({"ok": False, "error": "Categoría no encontrada."})

    if amount <= 0:
        return jsonify({"ok": False, "error": "Monto inválido."})

    contrib = CategoryContribution(
        user_id=g.user.id, category_id=c.id, date=d, amount=amount
    )
    db.session.add(contrib)
    db.session.commit()

    year, month = _current_year_month()
    state = build_month_state(g.user, year, month)
    return jsonify({"ok": True, "state": state})


@finance_bp.route("/api/saving_goal", methods=["POST"])
@login_required
def api_saving_goal():
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    target = float(data.get("target") or 0)
    deadline_txt = data.get("deadline")

    if not name or target <= 0:
        return jsonify({"ok": False, "error": "Nombre y monto objetivo son obligatorios."})

    deadline = None
    if deadline_txt:
        try:
            deadline = datetime.strptime(deadline_txt, "%Y-%m-%d").date()
        except Exception:
            deadline = None

    goal = SavingGoal(
        user_id=g.user.id, name=name, target_amount=target, deadline=deadline
    )
    db.session.add(goal)
    db.session.commit()

    year, month = _current_year_month()
    state = build_month_state(g.user, year, month)
    return jsonify({"ok": True, "state": state})


@finance_bp.route("/api/saving_contribution", methods=["POST"])
@login_required
def api_saving_contribution():
    data = request.get_json() or {}
    goal_id = data.get("goal_id")
    amount = float(data.get("amount") or 0)
    date_txt = data.get("date")

    goal = SavingGoal.query.filter_by(id=goal_id, user_id=g.user.id).first()
    if not goal:
        return jsonify({"ok": False, "error": "Meta de ahorro no encontrada."})

    if amount <= 0:
        return jsonify({"ok": False, "error": "Monto inválido."})

    try:
        d = datetime.strptime(date_txt, "%Y-%m-%d").date()
    except Exception:
        d = date.today()

    contrib = SavingContribution(goal_id=goal.id, amount=amount, date=d)
    db.session.add(contrib)
    db.session.commit()

    year, month = _current_year_month()
    state = build_month_state(g.user, year, month)
    return jsonify({"ok": True, "state": state})
