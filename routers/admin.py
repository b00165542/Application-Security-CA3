"""Admin dashboard: user management and global discount rules.

Product management routes live in routers/products.py.
"""

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from auth import hash_password, require_roles
from database import get_db
from models import ACTIVE_ORDER_STATUSES, ROLE_VALUES, DiscountRule, Order, Product, User, UserRole
from routers.cart import LOYALTY_DISCOUNT_RULE_ID
from schemas import AdminUserCreate, DiscountRuleUpdate, UserRoleUpdate, format_validation_errors
from templating import flash, render

router = APIRouter(prefix="/admin", tags=["admin"])

require_admin = require_roles(UserRole.ADMIN.value)


def _count_admins(db: Session) -> int:
    return db.scalar(select(func.count(User.id)).where(User.role == UserRole.ADMIN.value)) or 0


@router.get("")
def admin_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    products = db.scalars(select(Product).order_by(Product.type, Product.name)).all()
    users = db.scalars(select(User).order_by(User.role, User.username)).all()
    discount_rule = db.get(DiscountRule, LOYALTY_DISCOUNT_RULE_ID)
    stats = {
        "total_orders": db.scalar(select(func.count(Order.id))) or 0,
        "active_orders": db.scalar(select(func.count(Order.id)).where(Order.status.in_(ACTIVE_ORDER_STATUSES))) or 0,
        "revenue": db.scalar(select(func.coalesce(func.sum(Order.total_price), 0)).where(Order.status != "cancelled"))
        or 0,
    }
    return render(
        request,
        "admin_dashboard.html",
        {
            "products": products,
            "users": users,
            "discount_rule": discount_rule,
            "roles": ROLE_VALUES,
            "stats": stats,
        },
    )


@router.post("/users")
def create_user(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    role: str = Form(""),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    try:
        data = AdminUserCreate(username=username, password=password, role=role)
    except ValidationError as exc:
        flash(request, "; ".join(format_validation_errors(exc)), "error")
        return RedirectResponse("/admin#users", status_code=303)

    user = User(username=data.username, password_hash=hash_password(data.password), role=data.role)
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        flash(request, f"Username '{data.username}' is already taken.", "error")
        return RedirectResponse("/admin#users", status_code=303)

    flash(request, f"User '{user.username}' created with role '{user.role}'.", "success")
    return RedirectResponse("/admin#users", status_code=303)


@router.post("/users/{user_id}/role")
def change_user_role(
    request: Request,
    user_id: int,
    role: str = Form(""),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    try:
        data = UserRoleUpdate(role=role)
    except ValidationError as exc:
        flash(request, "; ".join(format_validation_errors(exc)), "error")
        return RedirectResponse("/admin#users", status_code=303)

    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    if user.id == admin.id and data.role != UserRole.ADMIN.value:
        flash(request, "You cannot remove your own admin role.", "error")
        return RedirectResponse("/admin#users", status_code=303)
    if user.role == UserRole.ADMIN.value and data.role != UserRole.ADMIN.value and _count_admins(db) <= 1:
        flash(request, "At least one admin account must remain.", "error")
        return RedirectResponse("/admin#users", status_code=303)

    user.role = data.role
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        flash(request, "Could not update the user's role.", "error")
        return RedirectResponse("/admin#users", status_code=303)

    flash(request, f"'{user.username}' is now '{user.role}'.", "success")
    return RedirectResponse("/admin#users", status_code=303)


@router.post("/users/{user_id}/delete")
def delete_user(
    request: Request,
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == admin.id:
        flash(request, "You cannot delete your own account.", "error")
        return RedirectResponse("/admin#users", status_code=303)

    username = user.username
    db.delete(user)  # orders keep existing; user_id is set to NULL
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        flash(request, "Could not delete the user.", "error")
        return RedirectResponse("/admin#users", status_code=303)

    flash(request, f"User '{username}' deleted.", "success")
    return RedirectResponse("/admin#users", status_code=303)


@router.post("/discount")
def update_discount_rule(
    request: Request,
    percentage: str = Form(""),
    min_total: str = Form(""),
    is_active: bool = Form(False),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    try:
        data = DiscountRuleUpdate(percentage=percentage, min_total=min_total, is_active=is_active)
    except ValidationError as exc:
        flash(request, "; ".join(format_validation_errors(exc)), "error")
        return RedirectResponse("/admin#discount", status_code=303)

    rule = db.get(DiscountRule, LOYALTY_DISCOUNT_RULE_ID)
    if rule is None:
        rule = DiscountRule(
            id=LOYALTY_DISCOUNT_RULE_ID,
            name="Loyalty discount",
            applies_to_role=UserRole.LOYALTY.value,
            percentage=data.percentage,
            min_total=data.min_total,
            is_active=data.is_active,
        )
        db.add(rule)
    else:
        rule.percentage = data.percentage
        rule.min_total = data.min_total
        rule.is_active = data.is_active

    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        flash(request, "Could not update the discount rule.", "error")
        return RedirectResponse("/admin#discount", status_code=303)

    state = "enabled" if rule.is_active else "disabled"
    flash(
        request,
        f"Loyalty discount {state}: {rule.percentage:g}% off orders over €{rule.min_total:.2f}.",
        "success",
    )
    return RedirectResponse("/admin#discount", status_code=303)
