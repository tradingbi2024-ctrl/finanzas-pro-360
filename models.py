from datetime import datetime, date

from db import db


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(180), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    is_admin = db.Column(db.Boolean, default=False)
    working_days = db.Column(db.Integer, default=26)  # 22–30

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login_at = db.Column(db.DateTime)
    last_active_at = db.Column(db.DateTime, default=datetime.utcnow)

    incomes = db.relationship(
        "DailyIncome",
        backref="user",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )
    categories = db.relationship(
        "Category",
        backref="user",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )
    saving_goals = db.relationship(
        "SavingGoal",
        backref="user",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )

    def __repr__(self):
        return f"<User {self.email}>"


class DailyIncome(db.Model):
    __tablename__ = "daily_incomes"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False
    )
    date = db.Column(db.Date, default=date.today, nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)


class Category(db.Model):
    __tablename__ = "categories"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False
    )

    name = db.Column(db.String(120), nullable=False)
    # Meta mensual fija (ej: cuota crédito, arriendo, etc.)
    monthly_goal = db.Column(db.Numeric(12, 2), nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    contributions = db.relationship(
        "CategoryContribution",
        backref="category",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )


class CategoryContribution(db.Model):
    __tablename__ = "category_contributions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False
    )
    category_id = db.Column(
        db.Integer, db.ForeignKey("categories.id"), nullable=False
    )
    date = db.Column(db.Date, default=date.today, nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)


class SavingGoal(db.Model):
    __tablename__ = "saving_goals"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False
    )

    name = db.Column(db.String(120), nullable=False)
    target_amount = db.Column(db.Numeric(12, 2), nullable=False)
    deadline = db.Column(db.Date, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    contributions = db.relationship(
        "SavingContribution",
        backref="goal",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )


class SavingContribution(db.Model):
    __tablename__ = "saving_contributions"

    id = db.Column(db.Integer, primary_key=True)
    goal_id = db.Column(
        db.Integer, db.ForeignKey("saving_goals.id"), nullable=False
    )
    date = db.Column(db.Date, default=date.today, nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
