"""Application entry point: FastAPI app, lifespan (DB creation + seeding) and root routes."""

import logging
import os
import secrets
from contextlib import asynccontextmanager
from typing import Optional
from urllib.parse import urlencode

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

import models  # noqa: F401  (registers models on Base.metadata)
from auth import NotAuthenticatedError, PermissionDeniedError, get_current_user, hash_password
from database import Base, SessionLocal, engine, get_db
from models import DiscountRule, Product, User, UserRole
from routers import admin, auth as auth_router, cart, orders, products
from routers.cart import LOYALTY_DISCOUNT_RULE_ID
from schemas import UserCreate, format_validation_errors
from templating import IMAGES_DIR, STATIC_DIR, flash, render

logger = logging.getLogger("coffee_shop")
logging.basicConfig(level=logging.INFO)

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    SECRET_KEY = secrets.token_urlsafe(32)
    logger.warning("SECRET_KEY not set - using a random key; sessions will reset on restart.")

SEED_DEMO_DATA = os.getenv("SEED_DEMO_DATA", "true").lower() in ("1", "true", "yes")


# --------------------------------------------------------------------------- #
# Initial data
# --------------------------------------------------------------------------- #
DEMO_PRODUCTS = [
    ("Espresso", "coffee", 2.50, "A rich, concentrated shot of our house blend."),
    ("Americano", "coffee", 3.00, "Espresso topped with hot water for a smooth, long coffee."),
    ("Cappuccino", "coffee", 3.80, "Espresso with steamed milk and a thick layer of foam."),
    ("Flat White", "coffee", 3.90, "Double ristretto with velvety micro-foam milk."),
    ("Caramel Latte", "coffee", 4.50, "Creamy latte with house-made caramel syrup."),
    ("Classic Hot Chocolate", "chocolate", 3.50, "Belgian milk chocolate melted into steamed milk."),
    ("Dark Hot Chocolate", "chocolate", 4.00, "70% dark chocolate for a deep, intense flavour."),
    ("White Hot Chocolate", "chocolate", 4.20, "Sweet white chocolate topped with whipped cream."),
]


class ConfigurationError(RuntimeError):
    """Raised at startup when required configuration is missing or invalid."""


# Seeded accounts: env var prefix, role, and the hint shown when the variables are missing.
# There are deliberately no default credentials: a missing or weak value stops startup
# instead of creating an account with a guessable password.
ADMIN_ACCOUNT = ("ADMIN", UserRole.ADMIN.value, "to create the first admin account (none exists yet)")
DEMO_ACCOUNTS = [
    ("DEMO_STAFF", UserRole.STAFF.value, "to create the demo staff account, or set SEED_DEMO_DATA=false"),
    ("DEMO_LOYALTY", UserRole.LOYALTY.value, "to create the demo loyalty account, or set SEED_DEMO_DATA=false"),
]


def _credentials_from_env(prefix: str, reason: str) -> UserCreate:
    """Read <prefix>_USERNAME / <prefix>_PASSWORD and validate them like a registration."""
    user_var, pass_var = f"{prefix}_USERNAME", f"{prefix}_PASSWORD"
    username = os.getenv(user_var, "").strip()
    password = os.getenv(pass_var, "")

    missing = [name for name, value in ((user_var, username), (pass_var, password)) if not value]
    if missing:
        raise ConfigurationError(
            f"{' and '.join(missing)} {'is' if len(missing) == 1 else 'are'} not set. "
            f"Set {user_var} and {pass_var} {reason}, then restart the app."
        )

    try:
        return UserCreate(username=username, password=password)
    except ValidationError as exc:
        details = "; ".join(format_validation_errors(exc))
        raise ConfigurationError(f"Invalid {user_var} / {pass_var}: {details}") from None


def _ensure_seeded_user(db: Session, prefix: str, role: str, reason: str, *, must_be_new: bool) -> None:
    """Create the account described by the env vars, refusing to clash with another role."""
    creds = _credentials_from_env(prefix, reason)
    existing = db.scalar(select(User).where(User.username == creds.username))
    if existing is None:
        db.add(User(username=creds.username, password_hash=hash_password(creds.password), role=role))
        db.flush()  # make the new account visible to the clash checks for the next accounts
        logger.info("Created %s account '%s'.", role, creds.username)
    elif must_be_new or existing.role != role:
        raise ConfigurationError(
            f"{prefix}_USERNAME '{creds.username}' is already used by an existing {existing.role} account. "
            f"Choose a different {prefix}_USERNAME."
        )


def seed_initial_data(db: Session) -> None:
    """Create the discount rule, a first admin, and (optionally) demo data."""
    if db.get(DiscountRule, LOYALTY_DISCOUNT_RULE_ID) is None:
        db.add(
            DiscountRule(
                id=LOYALTY_DISCOUNT_RULE_ID,
                name="Loyalty discount",
                applies_to_role=UserRole.LOYALTY.value,
                percentage=20.0,
                min_total=20.0,
                is_active=True,
            )
        )

    has_admin = db.scalar(select(func.count(User.id)).where(User.role == UserRole.ADMIN.value))
    if not has_admin:
        prefix, role, reason = ADMIN_ACCOUNT
        _ensure_seeded_user(db, prefix, role, reason, must_be_new=True)

    if SEED_DEMO_DATA:
        # Existing demo accounts are left as they are; their password is not reset from the env.
        for prefix, role, reason in DEMO_ACCOUNTS:
            _ensure_seeded_user(db, prefix, role, reason, must_be_new=False)

        if db.scalar(select(func.count(Product.id))) == 0:
            for name, ptype, price, description in DEMO_PRODUCTS:
                db.add(Product(name=name, type=ptype, price=price, description=description))
            logger.info("Seeded %d demo products.", len(DEMO_PRODUCTS))

    db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        try:
            seed_initial_data(db)
        except ConfigurationError as exc:
            logger.critical("Startup aborted: %s", exc)
            raise
    yield
    engine.dispose()


# --------------------------------------------------------------------------- #
# App setup
# --------------------------------------------------------------------------- #
app = FastAPI(title="Bean & Cocoa Coffee Shop", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    session_cookie="coffee_session",
    max_age=60 * 60 * 8,  # 8 hours
    same_site="lax",
    https_only=False,  # local development over http
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(auth_router.router)
app.include_router(products.router)
app.include_router(cart.router)
app.include_router(orders.router)
app.include_router(admin.router)


# --------------------------------------------------------------------------- #
# Error handling
# --------------------------------------------------------------------------- #
def _wants_json(request: Request) -> bool:
    return "/api" in request.url.path


@app.exception_handler(NotAuthenticatedError)
async def not_authenticated_handler(request: Request, exc: NotAuthenticatedError):
    flash(request, "Please log in to continue.", "warning")
    target = request.url.path if request.method == "GET" else "/"
    return RedirectResponse(f"/auth/login?{urlencode({'next': target})}", status_code=303)


@app.exception_handler(PermissionDeniedError)
async def permission_denied_handler(request: Request, exc: PermissionDeniedError):
    return render(
        request,
        "error.html",
        {"status_code": 403, "message": "You do not have permission to access this page."},
        status_code=403,
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if _wants_json(request):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    message = exc.detail if isinstance(exc.detail, str) else "Something went wrong."
    if exc.status_code == 404 and message == "Not Found":
        message = "The page you are looking for does not exist."
    return render(request, "error.html", {"status_code": exc.status_code, "message": message}, exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    if _wants_json(request):
        return JSONResponse({"detail": exc.errors()}, status_code=422)
    return render(
        request,
        "error.html",
        {"status_code": 422, "message": "The request contained invalid data."},
        status_code=422,
    )


# --------------------------------------------------------------------------- #
# Root routes
# --------------------------------------------------------------------------- #
@app.get("/", include_in_schema=False)
def home(
    request: Request,
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_current_user),
):
    coffees = db.scalars(select(Product).where(Product.type == "coffee").order_by(Product.name)).all()
    chocolates = db.scalars(select(Product).where(Product.type == "chocolate").order_by(Product.name)).all()
    discount_rule = db.get(DiscountRule, LOYALTY_DISCOUNT_RULE_ID)
    return render(
        request,
        "home.html",
        {"coffees": coffees, "chocolates": chocolates, "discount_rule": discount_rule},
    )


@app.get("/health", include_in_schema=False)
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
