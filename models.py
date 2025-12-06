from datetime import datetime, timedelta
from db import db

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True)
    email = db.Column(db.String(120), unique=True)
    password = db.Column(db.String(200))
    is_admin = db.Column(db.Boolean, default=False)
    last_login = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    finances = db.relationship("FinanceRecord", backref="user", lazy=True)
    savings = db.relationship("SavingRecord", backref="user", lazy=True)

    def inactive_days(self):
        return (datetime.utcnow() - self.last_login).days


class FinanceCategory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    name = db.Column(db.String(100))
    monthly_goal = db.Column(db.Float, default=0.0)


class FinanceRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    amount = db.Column(db.Float)
    date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class SavingRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    amount = db.Column(db.Float)
    date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
