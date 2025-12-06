from flask import Blueprint, request, session, jsonify
from models import FinanceRecord, FinanceCategory, SavingRecord, User
from db import db
from datetime import datetime, date

finance = Blueprint("finance", __name__)


def current_user():
    return User.query.get(session.get("user_id"))


@finance.route("/add_income", methods=["POST"])
def add_income():
    user = current_user()
    if not user:
        return jsonify({"ok": False})

    data = request.json
    amount = float(data.get("amount"))
    rec = FinanceRecord(user_id=user.id, amount=amount, date=date.today())
    db.session.add(rec)
    db.session.commit()

    return jsonify({"ok": True})


@finance.route("/add_saving", methods=["POST"])
def add_saving():
    user = current_user()
    if not user:
        return jsonify({"ok": False})

    data = request.json
    amount = float(data.get("amount"))
    rec = SavingRecord(user_id=user.id, amount=amount, date=date.today())
    db.session.add(rec)
    db.session.commit()

    return jsonify({"ok": True})


@finance.route("/add_category", methods=["POST"])
def add_category():
    user = current_user()
    data = request.json

    cat = FinanceCategory(
        user_id=user.id,
        name=data.get("name"),
        monthly_goal=float(data.get("monthly_goal"))
    )
    db.session.add(cat)
    db.session.commit()

    return jsonify({"ok": True})
