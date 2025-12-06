from flask import Blueprint, request, session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from models import User
from db import db
from datetime import datetime, timedelta

auth = Blueprint("auth", __name__)

SESSION_DURATION = timedelta(days=7)
DELETE_AFTER = 30

def cleanup_inactive_users():
    users = User.query.all()
    for u in users:
        if not u.is_admin and u.inactive_days() >= DELETE_AFTER:
            db.session.delete(u)
    db.session.commit()


@auth.route("/register", methods=["POST"])
def register():
    cleanup_inactive_users()

    data = request.json
    username = data.get("username")
    email = data.get("email")
    password = generate_password_hash(data.get("password"))

    # Si no existe admin, este será admin
    first_user = User.query.first()
    is_admin = False if first_user else True

    user = User(username=username, email=email, password=password, is_admin=is_admin)
    db.session.add(user)
    db.session.commit()

    return jsonify({"ok": True, "admin": is_admin})


@auth.route("/login", methods=["POST"])
def login():
    cleanup_inactive_users()

    data = request.json
    email = data.get("email")
    password = data.get("password")

    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({"ok": False, "error": "Usuario no encontrado"})

    if not check_password_hash(user.password, password):
        return jsonify({"ok": False, "error": "Contraseña incorrecta"})

    user.last_login = datetime.utcnow()
    db.session.commit()

    session["user_id"] = user.id
    session["expires_at"] = (datetime.utcnow() + SESSION_DURATION).timestamp()

    return jsonify({"ok": True, "is_admin": user.is_admin})
