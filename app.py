from flask import Flask, render_template, session, redirect
from db import init_db, db
from auth import auth
from finance import finance
import os
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev_key")

# RENDER POSTGRES INTERNAL URL
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
    "DATABASE_URL",
    "postgresql://postgresql15_mw9q_user:eRr1W7j2dV73PX5ouM9gp3SMwXDnxI5r@dpg-d4qb8cqli9vc739r29ig-a.internal:5432/postgresql15_mw9q"
)

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

init_db(app)

app.register_blueprint(auth, url_prefix="/auth")
app.register_blueprint(finance, url_prefix="/finance")


def session_active():
    exp = session.get("expires_at")
    if not exp:
        return False
    return datetime.utcnow().timestamp() < exp


@app.route("/")
def home():
    if not session_active():
        return render_template("login.html")
    return render_template("dashboard.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")
