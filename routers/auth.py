"""Login, logout and registration routes."""

from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth import authenticate_user, get_current_user, hash_password, login_user, logout_user
from database import get_db
from models import User, UserRole
from schemas import LoginForm, RegisterForm, format_validation_errors
from templating import flash, render, safe_redirect_target

router = APIRouter(prefix="/auth", tags=["auth"])


def _landing_page_for(user: User) -> str:
    if user.role == UserRole.ADMIN.value:
        return "/admin"
    if user.role == UserRole.STAFF.value:
        return "/orders/dashboard"
    return "/"


@router.get("/login")
def login_page(
    request: Request,
    next: Optional[str] = None,
    user: Optional[User] = Depends(get_current_user),
):
    if user is not None:
        return RedirectResponse(_landing_page_for(user), status_code=303)
    return render(request, "login.html", {"next": safe_redirect_target(next, "")})


@router.post("/login")
def login(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    next: str = Form(""),
    db: Session = Depends(get_db),
    _: Optional[User] = Depends(get_current_user),
):
    try:
        form = LoginForm(username=username, password=password)
    except ValidationError:
        return render(
            request,
            "login.html",
            {"errors": ["Please enter your username and password."], "username": username, "next": next},
            status_code=400,
        )

    user = authenticate_user(db, form.username, form.password)
    if user is None:
        return render(
            request,
            "login.html",
            {"errors": ["Invalid username or password."], "username": form.username, "next": next},
            status_code=401,
        )

    login_user(request, user)
    flash(request, f"Welcome back, {user.username}!", "success")
    target = safe_redirect_target(next, _landing_page_for(user))
    return RedirectResponse(target, status_code=303)


@router.post("/logout")
def logout(request: Request):
    logout_user(request)
    flash(request, "You have been logged out.", "info")
    return RedirectResponse("/", status_code=303)


@router.get("/register")
def register_page(request: Request, user: Optional[User] = Depends(get_current_user)):
    if user is not None:
        return RedirectResponse("/", status_code=303)
    return render(request, "register.html")


@router.post("/register")
def register(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    confirm_password: str = Form(""),
    db: Session = Depends(get_db),
    _: Optional[User] = Depends(get_current_user),
):
    try:
        form = RegisterForm(username=username, password=password, confirm_password=confirm_password)
    except ValidationError as exc:
        return render(
            request,
            "register.html",
            {"errors": format_validation_errors(exc), "username": username},
            status_code=400,
        )

    if db.scalar(select(User.id).where(User.username == form.username)) is not None:
        return render(
            request,
            "register.html",
            {"errors": ["That username is already taken."], "username": form.username},
            status_code=409,
        )

    # Public registration always creates loyalty members.
    user = User(
        username=form.username,
        password_hash=hash_password(form.password),
        role=UserRole.LOYALTY.value,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return render(
            request,
            "register.html",
            {"errors": ["That username is already taken."], "username": form.username},
            status_code=409,
        )
    db.refresh(user)

    login_user(request, user)
    flash(request, "Account created! You are now a loyalty member.", "success")
    return RedirectResponse("/", status_code=303)
