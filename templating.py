"""Jinja2 template setup plus helpers for flash messages and page rendering."""

from pathlib import Path
from typing import Any, Optional

from fastapi import Request
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
IMAGES_DIR = STATIC_DIR / "images"

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _format_eur(value: Any) -> str:
    try:
        return f"€{float(value):,.2f}"
    except (TypeError, ValueError):
        return "€0.00"


def _format_dt(value: Any) -> str:
    return value.strftime("%Y-%m-%d %H:%M") if value else ""


templates.env.filters["eur"] = _format_eur
templates.env.filters["dt"] = _format_dt


def flash(request: Request, message: str, category: str = "info") -> None:
    """Queue a one-time message to show on the next rendered page."""
    flashes = list(request.session.get("_flashes", []))
    flashes.append({"message": message, "category": category})
    request.session["_flashes"] = flashes


def pop_flashes(request: Request) -> list[dict[str, str]]:
    return request.session.pop("_flashes", [])


def cart_item_count(request: Request) -> int:
    cart = request.session.get("cart", {})
    return sum(int(q) for q in cart.values()) if isinstance(cart, dict) else 0


def render(
    request: Request,
    template_name: str,
    context: Optional[dict[str, Any]] = None,
    status_code: int = 200,
):
    """Render a template with the common layout context injected."""
    ctx: dict[str, Any] = {
        "current_user": getattr(request.state, "current_user", None),
        "cart_count": cart_item_count(request),
        "flashes": pop_flashes(request),
    }
    if context:
        ctx.update(context)
    return templates.TemplateResponse(request, template_name, ctx, status_code=status_code)


def safe_redirect_target(target: Optional[str], default: str = "/") -> str:
    """Only allow relative, same-site redirect targets."""
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return default
