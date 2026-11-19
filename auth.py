"""Authentication helpers: password hashing and current-user dependencies."""

from collections.abc import Callable
from typing import Optional

from fastapi import Depends, Request
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_db
from models import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Pre-computed hash used to keep login timing similar for unknown usernames.
_DUMMY_HASH = pwd_context.hash("dummy-password-for-timing")

SESSION_USER_KEY = "user_id"


class NotAuthenticatedError(Exception):
    """Raised when a route requires a logged-in user and there is none."""


class PermissionDeniedError(Exception):
    """Raised when the logged-in user lacks the required role."""


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return pwd_context.verify(password, password_hash)
    except (ValueError, TypeError):
        return False


def authenticate_user(db: Session, username: str, password: str) -> Optional[User]:
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        verify_password(password, _DUMMY_HASH)
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def login_user(request: Request, user: User) -> None:
    """Store the user in the session, keeping the shopping cart."""
    cart = request.session.get("cart", {})
    request.session.clear()
    request.session[SESSION_USER_KEY] = user.id
    if cart:
        request.session["cart"] = cart


def logout_user(request: Request) -> None:
    request.session.clear()


def get_current_user(request: Request, db: Session = Depends(get_db)) -> Optional[User]:
    """Return the logged-in user or None for guests.

    The user is also stored on request.state so templates can access it.
    """
    user: Optional[User] = None
    user_id = request.session.get(SESSION_USER_KEY)
    if user_id is not None:
        user = db.get(User, user_id)
        if user is None:
            # Stale session (user deleted) - drop it.
            request.session.pop(SESSION_USER_KEY, None)
    request.state.current_user = user
    return user


def require_login(user: Optional[User] = Depends(get_current_user)) -> User:
    if user is None:
        raise NotAuthenticatedError()
    return user


def require_roles(*roles: str) -> Callable[..., User]:
    """Dependency factory: allow only users whose role is in `roles`."""

    def dependency(user: User = Depends(require_login)) -> User:
        if user.role not in roles:
            raise PermissionDeniedError()
        return user

    return dependency
