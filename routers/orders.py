"""Order history (customers) and fulfilment dashboard (staff/admin)."""

from typing import Literal

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from auth import require_login, require_roles
from database import get_db
from models import (
    ACTIVE_ORDER_STATUSES,
    ORDER_STATUS_VALUES,
    PAST_ORDER_STATUSES,
    Order,
    User,
    UserRole,
)
from schemas import OrderStatusUpdate, format_validation_errors
from templating import flash, render, safe_redirect_target

router = APIRouter(prefix="/orders", tags=["orders"])

require_staff = require_roles(UserRole.STAFF.value, UserRole.ADMIN.value)


@router.get("/my")
def my_orders(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_login),
):
    orders = db.scalars(
        select(Order)
        .options(selectinload(Order.items))
        .where(Order.user_id == user.id)
        .order_by(Order.created_at.desc())
    ).all()
    return render(request, "my_orders.html", {"orders": orders})


@router.get("/dashboard")
def fulfilment_dashboard(
    request: Request,
    view: Literal["active", "past", "all"] = "active",
    db: Session = Depends(get_db),
    _: User = Depends(require_staff),
):
    query = select(Order).options(selectinload(Order.items), selectinload(Order.user))
    if view == "active":
        # Oldest first so baristas work through the queue in order.
        query = query.where(Order.status.in_(ACTIVE_ORDER_STATUSES)).order_by(Order.created_at.asc())
    elif view == "past":
        query = query.where(Order.status.in_(PAST_ORDER_STATUSES)).order_by(Order.created_at.desc())
    else:
        query = query.order_by(Order.created_at.desc())
    orders = db.scalars(query).all()
    return render(
        request,
        "staff_dashboard.html",
        {"orders": orders, "view": view, "statuses": ORDER_STATUS_VALUES},
    )


@router.get("/{order_id}")
def order_detail(
    request: Request,
    order_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_login),
):
    order = db.scalar(
        select(Order).options(selectinload(Order.items), selectinload(Order.user)).where(Order.id == order_id)
    )
    # Customers may only see their own orders; return 404 to avoid revealing other orders.
    if order is None or (not user.is_staff_or_admin and order.user_id != user.id):
        raise HTTPException(status_code=404, detail="Order not found")
    return render(request, "order_detail.html", {"order": order, "statuses": ORDER_STATUS_VALUES})


@router.post("/{order_id}/status")
def update_order_status(
    request: Request,
    order_id: int,
    status: str = Form(""),
    next: str = Form("/orders/dashboard"),
    db: Session = Depends(get_db),
    _: User = Depends(require_staff),
):
    redirect_to = safe_redirect_target(next, "/orders/dashboard")
    try:
        data = OrderStatusUpdate(status=status)
    except ValidationError as exc:
        flash(request, "; ".join(format_validation_errors(exc)), "error")
        return RedirectResponse(redirect_to, status_code=303)

    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.order_type == "pickup" and data.status == "delivering":
        flash(request, "Pickup orders cannot be set to 'delivering'.", "error")
        return RedirectResponse(redirect_to, status_code=303)

    order.status = data.status
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        flash(request, "Could not update the order status.", "error")
        return RedirectResponse(redirect_to, status_code=303)

    flash(request, f"Order #{order.id} is now '{order.status}'.", "success")
    return RedirectResponse(redirect_to, status_code=303)
