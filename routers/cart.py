"""Shopping cart, pricing and checkout routes.

The cart lives in the signed session cookie as {"<product_id>": quantity}.
Prices are ALWAYS re-read from the database; the client never supplies prices.
"""

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from auth import get_current_user
from database import get_db
from models import DiscountRule, Order, OrderItem, OrderStatus, Product, User
from schemas import CartItemAdd, CartItemUpdate, CheckoutForm, format_validation_errors
from templating import flash, render, safe_redirect_target

router = APIRouter(prefix="/cart", tags=["cart"])

CENT = Decimal("0.01")
MAX_QUANTITY_PER_ITEM = 99
LOYALTY_DISCOUNT_RULE_ID = 1


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _dec(value: float) -> Decimal:
    return Decimal(str(value))


# --------------------------------------------------------------------------- #
# Session cart helpers
# --------------------------------------------------------------------------- #
def get_cart(request: Request) -> dict[str, int]:
    raw = request.session.get("cart", {})
    if not isinstance(raw, dict):
        return {}
    cart: dict[str, int] = {}
    for key, qty in raw.items():
        try:
            pid, q = int(key), int(qty)
        except (TypeError, ValueError):
            continue
        if pid > 0 and q > 0:
            cart[str(pid)] = min(q, MAX_QUANTITY_PER_ITEM)
    return cart


def save_cart(request: Request, cart: dict[str, int]) -> None:
    if cart:
        request.session["cart"] = cart
    else:
        request.session.pop("cart", None)


# --------------------------------------------------------------------------- #
# Pricing
# --------------------------------------------------------------------------- #
@dataclass
class CartLine:
    product: Product
    quantity: int
    line_total: Decimal


@dataclass
class CartSummary:
    lines: list[CartLine] = field(default_factory=list)
    subtotal: Decimal = Decimal("0.00")
    discount: Decimal = Decimal("0.00")
    total: Decimal = Decimal("0.00")
    discount_rule: Optional[DiscountRule] = None

    @property
    def is_empty(self) -> bool:
        return not self.lines


def get_loyalty_discount_rule(db: Session) -> Optional[DiscountRule]:
    return db.get(DiscountRule, LOYALTY_DISCOUNT_RULE_ID)


def compute_discount(subtotal: Decimal, user: Optional[User], rule: Optional[DiscountRule]) -> Decimal:
    """Loyalty members get rule.percentage off when the subtotal exceeds rule.min_total."""
    if rule is None or not rule.is_active or user is None:
        return Decimal("0.00")
    if user.role != rule.applies_to_role:
        return Decimal("0.00")
    if subtotal <= _dec(rule.min_total):
        return Decimal("0.00")
    return _money(subtotal * _dec(rule.percentage) / Decimal(100))


def build_cart_summary(request: Request, db: Session, user: Optional[User]) -> CartSummary:
    cart = get_cart(request)
    summary = CartSummary()
    if not cart:
        save_cart(request, cart)
        return summary

    ids = [int(pid) for pid in cart]
    products = {p.id: p for p in db.scalars(select(Product).where(Product.id.in_(ids))).all()}

    # Drop items whose product no longer exists.
    cleaned = {pid: q for pid, q in cart.items() if int(pid) in products}
    if cleaned != cart:
        flash(request, "Some items were removed from your cart because they are no longer available.", "warning")
    save_cart(request, cleaned)

    for pid, qty in cleaned.items():
        product = products[int(pid)]
        line_total = _money(_dec(product.price) * qty)
        summary.lines.append(CartLine(product=product, quantity=qty, line_total=line_total))
        summary.subtotal += line_total

    summary.subtotal = _money(summary.subtotal)
    rule = get_loyalty_discount_rule(db)
    summary.discount_rule = rule
    summary.discount = compute_discount(summary.subtotal, user, rule)
    summary.total = _money(summary.subtotal - summary.discount)
    return summary


# --------------------------------------------------------------------------- #
# Cart routes
# --------------------------------------------------------------------------- #
@router.get("")
def view_cart(
    request: Request,
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_current_user),
):
    summary = build_cart_summary(request, db, user)
    return render(request, "cart.html", {"summary": summary})


@router.post("/add")
def add_to_cart(
    request: Request,
    product_id: str = Form(""),
    quantity: str = Form("1"),
    next: str = Form("/cart"),
    db: Session = Depends(get_db),
    _: Optional[User] = Depends(get_current_user),
):
    redirect_to = safe_redirect_target(next, "/cart")
    try:
        item = CartItemAdd(product_id=product_id, quantity=quantity)
    except ValidationError as exc:
        flash(request, "; ".join(format_validation_errors(exc)), "error")
        return RedirectResponse(redirect_to, status_code=303)

    product = db.get(Product, item.product_id)
    if product is None:
        flash(request, "That product does not exist.", "error")
        return RedirectResponse(redirect_to, status_code=303)

    cart = get_cart(request)
    key = str(product.id)
    new_qty = cart.get(key, 0) + item.quantity
    if new_qty > MAX_QUANTITY_PER_ITEM:
        new_qty = MAX_QUANTITY_PER_ITEM
        flash(request, f"Maximum quantity per item is {MAX_QUANTITY_PER_ITEM}.", "warning")
    cart[key] = new_qty
    save_cart(request, cart)
    flash(request, f"Added {item.quantity} x {product.name} to your cart.", "success")
    return RedirectResponse(redirect_to, status_code=303)


@router.post("/update")
def update_cart_item(
    request: Request,
    product_id: str = Form(""),
    quantity: str = Form(""),
):
    try:
        item = CartItemUpdate(product_id=product_id, quantity=quantity)
    except ValidationError as exc:
        flash(request, "; ".join(format_validation_errors(exc)), "error")
        return RedirectResponse("/cart", status_code=303)

    cart = get_cart(request)
    key = str(item.product_id)
    if key not in cart:
        flash(request, "That item is not in your cart.", "error")
    elif item.quantity == 0:
        cart.pop(key)
        flash(request, "Item removed from cart.", "info")
    else:
        cart[key] = item.quantity
        flash(request, "Cart updated.", "success")
    save_cart(request, cart)
    return RedirectResponse("/cart", status_code=303)


@router.post("/remove/{product_id}")
def remove_cart_item(request: Request, product_id: int):
    cart = get_cart(request)
    if cart.pop(str(product_id), None) is not None:
        flash(request, "Item removed from cart.", "info")
    save_cart(request, cart)
    return RedirectResponse("/cart", status_code=303)


@router.post("/clear")
def clear_cart(request: Request):
    save_cart(request, {})
    flash(request, "Your cart has been emptied.", "info")
    return RedirectResponse("/cart", status_code=303)


# --------------------------------------------------------------------------- #
# Checkout
# --------------------------------------------------------------------------- #
@router.get("/checkout")
def checkout_page(
    request: Request,
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_current_user),
):
    summary = build_cart_summary(request, db, user)
    if summary.is_empty:
        flash(request, "Your cart is empty.", "warning")
        return RedirectResponse("/cart", status_code=303)
    form = {"customer_name": user.username if user else "", "order_type": "pickup"}
    return render(request, "checkout.html", {"summary": summary, "form": form})


@router.post("/checkout")
def pay_now(
    request: Request,
    customer_name: str = Form(""),
    order_type: str = Form(""),
    delivery_address: str = Form(""),
    delivery_instructions: str = Form(""),
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_current_user),
):
    """'Pay Now': validate the checkout form, create the order and clear the cart.

    No real payment provider is integrated; payment is simulated as successful.
    """
    summary = build_cart_summary(request, db, user)
    if summary.is_empty:
        flash(request, "Your cart is empty.", "warning")
        return RedirectResponse("/cart", status_code=303)

    form_values = {
        "customer_name": customer_name,
        "order_type": order_type,
        "delivery_address": delivery_address,
        "delivery_instructions": delivery_instructions,
    }
    try:
        checkout = CheckoutForm(**form_values)
    except ValidationError as exc:
        return render(
            request,
            "checkout.html",
            {"summary": summary, "form": form_values, "errors": format_validation_errors(exc)},
            status_code=400,
        )

    order = Order(
        user_id=user.id if user else None,
        customer_name=checkout.customer_name,
        subtotal=float(summary.subtotal),
        discount_applied=float(summary.discount),
        total_price=float(summary.total),
        status=OrderStatus.PENDING.value,
        order_type=checkout.order_type,
        delivery_address=checkout.delivery_address,
        delivery_instructions=checkout.delivery_instructions,
    )
    for line in summary.lines:
        order.items.append(
            OrderItem(
                product_id=line.product.id,
                product_name=line.product.name,
                quantity=line.quantity,
                unit_price=line.product.price,
            )
        )

    db.add(order)
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        return render(
            request,
            "checkout.html",
            {
                "summary": summary,
                "form": form_values,
                "errors": ["We could not process your order. Please try again."],
            },
            status_code=500,
        )

    save_cart(request, {})
    request.session["last_order_id"] = order.id
    return RedirectResponse("/cart/success", status_code=303)


@router.get("/success")
def order_success(
    request: Request,
    db: Session = Depends(get_db),
    _: Optional[User] = Depends(get_current_user),
):
    order_id = request.session.get("last_order_id")
    order = None
    if order_id is not None:
        order = db.scalar(select(Order).options(selectinload(Order.items)).where(Order.id == order_id))
    if order is None:
        return RedirectResponse("/", status_code=303)
    return render(request, "order_success.html", {"order": order})
