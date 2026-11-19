"""Pydantic models used to validate all user input and serialise API output."""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

USERNAME_PATTERN = r"^[A-Za-z0-9_.-]+$"

RoleLiteral = Literal["loyalty", "staff", "admin"]
ProductTypeLiteral = Literal["coffee", "chocolate"]
OrderStatusLiteral = Literal["pending", "preparing", "ready", "delivering", "completed", "cancelled"]
OrderTypeLiteral = Literal["pickup", "delivery"]


def format_validation_errors(exc: ValidationError) -> list[str]:
    """Turn a Pydantic ValidationError into human readable messages for templates."""
    messages: list[str] = []
    for err in exc.errors():
        msg = err.get("msg", "Invalid value")
        if msg.startswith("Value error, "):
            msg = msg[len("Value error, "):]
        loc = [str(part) for part in err.get("loc", ()) if part != "__root__"]
        field = loc[-1].replace("_", " ").capitalize() if loc else ""
        messages.append(f"{field}: {msg}" if field else msg)
    return messages


def _strip_or_none(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    return value or None


# --------------------------------------------------------------------------- #
# Authentication / users
# --------------------------------------------------------------------------- #
class LoginForm(BaseModel):
    username: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=72)

    @field_validator("username")
    @classmethod
    def strip_username(cls, v: str) -> str:
        return v.strip()


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=USERNAME_PATTERN)
    # bcrypt only uses the first 72 bytes of a password.
    password: str = Field(min_length=8, max_length=72)

    @field_validator("username", mode="before")
    @classmethod
    def strip_username(cls, v):
        return v.strip() if isinstance(v, str) else v


class RegisterForm(UserCreate):
    confirm_password: str

    @model_validator(mode="after")
    def passwords_match(self) -> "RegisterForm":
        if self.password != self.confirm_password:
            raise ValueError("Passwords do not match")
        return self


class AdminUserCreate(UserCreate):
    role: RoleLiteral


class UserRoleUpdate(BaseModel):
    role: RoleLiteral


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    role: RoleLiteral


# --------------------------------------------------------------------------- #
# Products
# --------------------------------------------------------------------------- #
class ProductBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    type: ProductTypeLiteral
    price: float = Field(gt=0, le=1000)
    description: str = Field(default="", max_length=1000)

    @field_validator("name", "description", mode="before")
    @classmethod
    def strip_text(cls, v):
        return v.strip() if isinstance(v, str) else v

    @field_validator("price")
    @classmethod
    def round_price(cls, v: float) -> float:
        return round(v, 2)


class ProductCreate(ProductBase):
    pass


class ProductUpdate(ProductBase):
    pass


class ProductOut(ProductBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    image_path: Optional[str] = None


# --------------------------------------------------------------------------- #
# Cart / checkout
# --------------------------------------------------------------------------- #
class CartItemAdd(BaseModel):
    product_id: int = Field(gt=0)
    quantity: int = Field(default=1, ge=1, le=99)


class CartItemUpdate(BaseModel):
    product_id: int = Field(gt=0)
    # 0 removes the item from the cart.
    quantity: int = Field(ge=0, le=99)


class CheckoutForm(BaseModel):
    customer_name: str = Field(min_length=1, max_length=100)
    order_type: OrderTypeLiteral
    delivery_address: Optional[str] = Field(default=None, max_length=300)
    delivery_instructions: Optional[str] = Field(default=None, max_length=500)

    @field_validator("customer_name", mode="before")
    @classmethod
    def strip_name(cls, v):
        return v.strip() if isinstance(v, str) else v

    @field_validator("delivery_address", "delivery_instructions", mode="before")
    @classmethod
    def blank_to_none(cls, v):
        return _strip_or_none(v) if isinstance(v, str) or v is None else v

    @model_validator(mode="after")
    def address_required_for_delivery(self) -> "CheckoutForm":
        if self.order_type == "delivery" and not self.delivery_address:
            raise ValueError("A delivery address is required for delivery orders")
        if self.order_type == "pickup":
            self.delivery_address = None
        return self


# --------------------------------------------------------------------------- #
# Orders / discounts
# --------------------------------------------------------------------------- #
class OrderStatusUpdate(BaseModel):
    status: OrderStatusLiteral


class DiscountRuleUpdate(BaseModel):
    percentage: float = Field(ge=0, le=100)
    min_total: float = Field(ge=0, le=10000)
    is_active: bool = False

    @field_validator("percentage", "min_total")
    @classmethod
    def round_values(cls, v: float) -> float:
        return round(v, 2)
