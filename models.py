"""SQLAlchemy ORM models."""

import enum
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UserRole(str, enum.Enum):
    LOYALTY = "loyalty"
    STAFF = "staff"
    ADMIN = "admin"


class ProductType(str, enum.Enum):
    COFFEE = "coffee"
    CHOCOLATE = "chocolate"


class OrderStatus(str, enum.Enum):
    PENDING = "pending"
    PREPARING = "preparing"
    READY = "ready"
    DELIVERING = "delivering"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class OrderType(str, enum.Enum):
    PICKUP = "pickup"
    DELIVERY = "delivery"


ROLE_VALUES = tuple(r.value for r in UserRole)
PRODUCT_TYPE_VALUES = tuple(t.value for t in ProductType)
ORDER_STATUS_VALUES = tuple(s.value for s in OrderStatus)
ORDER_TYPE_VALUES = tuple(t.value for t in OrderType)
ACTIVE_ORDER_STATUSES = (
    OrderStatus.PENDING.value,
    OrderStatus.PREPARING.value,
    OrderStatus.READY.value,
    OrderStatus.DELIVERING.value,
)
PAST_ORDER_STATUSES = (OrderStatus.COMPLETED.value, OrderStatus.CANCELLED.value)


def _in_check(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{v}'" for v in values)
    return f"{column} IN ({quoted})"


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint(_in_check("role", ROLE_VALUES), name="ck_users_role"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default=UserRole.LOYALTY.value)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    orders: Mapped[list["Order"]] = relationship(back_populates="user")

    @property
    def is_admin(self) -> bool:
        return self.role == UserRole.ADMIN.value

    @property
    def is_staff_or_admin(self) -> bool:
        return self.role in (UserRole.STAFF.value, UserRole.ADMIN.value)


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint(_in_check("type", PRODUCT_TYPE_VALUES), name="ck_products_type"),
        CheckConstraint("price > 0", name="ck_products_price_positive"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Path relative to the ./static directory, e.g. "images/abc123.png"
    image_path: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint(_in_check("status", ORDER_STATUS_VALUES), name="ck_orders_status"),
        CheckConstraint(_in_check("order_type", ORDER_TYPE_VALUES), name="ck_orders_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Nullable: guests check out without an account; kept if a user is deleted.
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    customer_name: Mapped[str] = mapped_column(String(100), nullable=False)
    subtotal: Mapped[float] = mapped_column(Float, nullable=False)
    discount_applied: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_price: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=OrderStatus.PENDING.value)
    order_type: Mapped[str] = mapped_column(String(20), nullable=False)
    delivery_address: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    delivery_instructions: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    user: Mapped[Optional[User]] = relationship(back_populates="orders")
    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="OrderItem.id"
    )

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_ORDER_STATUSES


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = (CheckConstraint("quantity > 0", name="ck_order_items_quantity_positive"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    # Nullable so historic orders survive product deletion.
    product_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), nullable=True
    )
    # Snapshot of the product name at purchase time.
    product_name: Mapped[str] = mapped_column(String(100), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[float] = mapped_column(Float, nullable=False)

    order: Mapped[Order] = relationship(back_populates="items")
    product: Mapped[Optional[Product]] = relationship()

    @property
    def line_total(self) -> float:
        return round(self.unit_price * self.quantity, 2)


class DiscountRule(Base):
    """Global discount configuration, editable by admins.

    The application uses a single row (id=1): the loyalty discount.
    """

    __tablename__ = "discount_rules"
    __table_args__ = (
        CheckConstraint("percentage >= 0 AND percentage <= 100", name="ck_discount_percentage"),
        CheckConstraint("min_total >= 0", name="ck_discount_min_total"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    applies_to_role: Mapped[str] = mapped_column(String(20), nullable=False, default=UserRole.LOYALTY.value)
    percentage: Mapped[float] = mapped_column(Float, nullable=False)
    # Discount applies when the cart subtotal is strictly greater than this value.
    min_total: Mapped[float] = mapped_column(Float, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
