"""Product catalogue (public) and product management (admin) routes."""

import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from auth import get_current_user, require_roles
from database import get_db
from models import OrderItem, Product, User, UserRole
from schemas import ProductCreate, ProductOut, ProductUpdate, format_validation_errors
from templating import IMAGES_DIR, flash, render

router = APIRouter(prefix="/products", tags=["products"])

require_admin = require_roles(UserRole.ADMIN.value)

ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
MAX_IMAGE_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB


class ImageUploadError(ValueError):
    pass


def _has_file(upload: Optional[UploadFile]) -> bool:
    return upload is not None and bool(upload.filename)


async def save_product_image(upload: UploadFile) -> str:
    """Save an uploaded image to ./static/images and return its path relative to /static."""
    extension = Path(upload.filename or "").suffix.lower()
    if extension not in ALLOWED_IMAGE_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_IMAGE_EXTENSIONS))
        raise ImageUploadError(f"Unsupported image type. Allowed: {allowed}")

    content = await upload.read(MAX_IMAGE_SIZE_BYTES + 1)
    await upload.close()
    if not content:
        raise ImageUploadError("The uploaded image is empty.")
    if len(content) > MAX_IMAGE_SIZE_BYTES:
        raise ImageUploadError("The image is too large (maximum 5 MB).")

    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}{extension}"
    (IMAGES_DIR / filename).write_bytes(content)
    return f"images/{filename}"


def delete_product_image(image_path: Optional[str]) -> None:
    """Delete a previously uploaded image file (never the bundled placeholders)."""
    if not image_path or not image_path.startswith("images/"):
        return
    filename = Path(image_path).name
    if filename.startswith("placeholder"):
        return
    try:
        (IMAGES_DIR / filename).unlink(missing_ok=True)
    except OSError:
        pass


def get_product_or_404(db: Session, product_id: int) -> Product:
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


# --------------------------------------------------------------------------- #
# Public catalogue
# --------------------------------------------------------------------------- #
@router.get("")
def list_products(
    request: Request,
    type: Optional[str] = None,
    db: Session = Depends(get_db),
    _: Optional[User] = Depends(get_current_user),
):
    query = select(Product).order_by(Product.type, Product.name)
    selected_type = type if type in ("coffee", "chocolate") else None
    if selected_type:
        query = query.where(Product.type == selected_type)
    products = db.scalars(query).all()
    return render(request, "products.html", {"products": products, "selected_type": selected_type})


@router.get("/api", response_model=list[ProductOut])
def list_products_json(db: Session = Depends(get_db)):
    """JSON listing of the menu."""
    return db.scalars(select(Product).order_by(Product.id)).all()


# --------------------------------------------------------------------------- #
# Admin: create
# (declared before /{product_id} so "new" is not parsed as an id)
# --------------------------------------------------------------------------- #
@router.get("/new")
def new_product_page(request: Request, _: User = Depends(require_admin)):
    return render(request, "product_form.html", {"product": None, "form": {}})


@router.post("")
async def create_product(
    request: Request,
    name: str = Form(""),
    type: str = Form(""),
    price: str = Form(""),
    description: str = Form(""),
    image: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    form_values = {"name": name, "type": type, "price": price, "description": description}
    try:
        data = ProductCreate(**form_values)
    except ValidationError as exc:
        return render(
            request,
            "product_form.html",
            {"product": None, "form": form_values, "errors": format_validation_errors(exc)},
            status_code=400,
        )

    image_path: Optional[str] = None
    if _has_file(image):
        try:
            image_path = await save_product_image(image)
        except ImageUploadError as exc:
            return render(
                request,
                "product_form.html",
                {"product": None, "form": form_values, "errors": [str(exc)]},
                status_code=400,
            )

    product = Product(**data.model_dump(), image_path=image_path)
    db.add(product)
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        delete_product_image(image_path)
        flash(request, "Could not save the product. Please try again.", "error")
        return RedirectResponse("/products/new", status_code=303)

    flash(request, f"Product '{product.name}' created.", "success")
    return RedirectResponse("/admin", status_code=303)


# --------------------------------------------------------------------------- #
# Public: detail
# --------------------------------------------------------------------------- #
@router.get("/{product_id}")
def product_detail(
    request: Request,
    product_id: int,
    db: Session = Depends(get_db),
    _: Optional[User] = Depends(get_current_user),
):
    product = get_product_or_404(db, product_id)
    return render(request, "product_detail.html", {"product": product})


# --------------------------------------------------------------------------- #
# Admin: update / image upload / delete
# --------------------------------------------------------------------------- #
@router.get("/{product_id}/edit")
def edit_product_page(
    request: Request,
    product_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    product = get_product_or_404(db, product_id)
    form_values = {
        "name": product.name,
        "type": product.type,
        "price": f"{product.price:.2f}",
        "description": product.description,
    }
    return render(request, "product_form.html", {"product": product, "form": form_values})


@router.post("/{product_id}/edit")
async def update_product(
    request: Request,
    product_id: int,
    name: str = Form(""),
    type: str = Form(""),
    price: str = Form(""),
    description: str = Form(""),
    image: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    product = get_product_or_404(db, product_id)
    form_values = {"name": name, "type": type, "price": price, "description": description}
    try:
        data = ProductUpdate(**form_values)
    except ValidationError as exc:
        return render(
            request,
            "product_form.html",
            {"product": product, "form": form_values, "errors": format_validation_errors(exc)},
            status_code=400,
        )

    old_image = product.image_path
    new_image: Optional[str] = None
    if _has_file(image):
        try:
            new_image = await save_product_image(image)
        except ImageUploadError as exc:
            return render(
                request,
                "product_form.html",
                {"product": product, "form": form_values, "errors": [str(exc)]},
                status_code=400,
            )

    for field, value in data.model_dump().items():
        setattr(product, field, value)
    if new_image:
        product.image_path = new_image

    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        delete_product_image(new_image)
        flash(request, "Could not update the product. Please try again.", "error")
        return RedirectResponse(f"/products/{product_id}/edit", status_code=303)

    if new_image:
        delete_product_image(old_image)
    flash(request, f"Product '{product.name}' updated.", "success")
    return RedirectResponse("/admin", status_code=303)


@router.post("/{product_id}/image")
async def upload_product_image(
    request: Request,
    product_id: int,
    image: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    product = get_product_or_404(db, product_id)
    if not _has_file(image):
        flash(request, "Please choose an image to upload.", "error")
        return RedirectResponse("/admin", status_code=303)
    try:
        new_image = await save_product_image(image)
    except ImageUploadError as exc:
        flash(request, str(exc), "error")
        return RedirectResponse("/admin", status_code=303)

    old_image = product.image_path
    product.image_path = new_image
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        delete_product_image(new_image)
        flash(request, "Could not save the image. Please try again.", "error")
        return RedirectResponse("/admin", status_code=303)

    delete_product_image(old_image)
    flash(request, f"Image updated for '{product.name}'.", "success")
    return RedirectResponse("/admin", status_code=303)


@router.post("/{product_id}/delete")
def delete_product(
    request: Request,
    product_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    product = get_product_or_404(db, product_id)
    image_path = product.image_path
    name = product.name

    # Detach historic order lines (they keep their name/price snapshot).
    db.execute(update(OrderItem).where(OrderItem.product_id == product_id).values(product_id=None))
    db.delete(product)
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        flash(request, "Could not delete the product.", "error")
        return RedirectResponse("/admin", status_code=303)

    delete_product_image(image_path)

    # Remove it from this admin's own cart if present.
    cart = dict(request.session.get("cart", {}))
    if cart.pop(str(product_id), None) is not None:
        request.session["cart"] = cart

    flash(request, f"Product '{name}' deleted.", "success")
    return RedirectResponse("/admin", status_code=303)
