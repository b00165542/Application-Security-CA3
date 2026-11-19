# Bean & Cocoa Coffee Shop (v0 baseline)

A server-rendered coffee shop web application built with **FastAPI**, **SQLAlchemy/SQLite** and **Jinja2**.
This is the **baseline (v0)** for a Secure Software Development Life Cycle (S-SDLC) project. It is fully
functional but **intentionally has no advanced security hardening** (no rate limiting, CSP, CSRF tokens, etc.).
That hardening is added in a later phase.

## Architecture

```
 Web UI (browser: guest / loyalty / staff / admin)
        │  HTTP requests / HTML responses
 ───────┼───────────────  front end / server trust boundary
        ▼
 FastAPI server (Jinja2 templates, session cookie, static files)
        │  SQL queries / results (SQLAlchemy)
        ▼
 Local SQLite database (coffee_shop.db) + ./static/images for product images
```

Everything runs on one machine, so the whole setup can be started locally with a single command.

## Features

| Role | What they can do |
|------|------------------|
| **Guest** | Browse the menu, add to cart, check out (pickup or delivery) without an account |
| **Loyalty** | Everything a guest can do, plus a **20% discount when the cart total is over €20**, and their own order history |
| **Staff** | View active/past orders with items, totals and delivery/pickup instructions; update order status |
| **Admin** | Everything staff can do, plus add/edit/delete products, upload product images, manage users and roles, change the discount rule |

- The cart is stored in a signed session cookie. Prices and discounts are always recalculated on the server.
- **Pay Now** simulates payment: it saves the order, clears the cart and shows a confirmation page. No real payment provider is used.
- Order statuses: `pending → preparing → ready / delivering → completed` (or `cancelled`).

## Project structure

```
.
├── main.py              # App setup, lifespan (create tables + seed data), error handlers, home route
├── database.py          # SQLAlchemy engine, session factory, Base, get_db dependency
├── models.py            # User, Product, Order, OrderItem, DiscountRule
├── schemas.py           # Pydantic models for validating all input
├── auth.py              # Password hashing (passlib/bcrypt), current-user and role dependencies
├── templating.py        # Jinja2 setup, flash messages, render helper
├── routers/
│   ├── auth.py          # /auth/login, /auth/logout, /auth/register
│   ├── products.py      # /products: menu, product CRUD, image upload
│   ├── cart.py          # /cart: cart, pricing, checkout ("Pay Now")
│   ├── orders.py        # /orders: customer history, staff dashboard, status updates
│   └── admin.py         # /admin: dashboard, user management, discount rule
├── templates/           # Jinja2 HTML templates
├── static/
│   ├── css/style.css
│   └── images/          # Uploaded product images (and bundled placeholders)
└── requirements.txt
```

## Running locally

### Prerequisites

- Python **3.10 or newer** (tested with 3.13)
- `pip`

### 1. Create and activate a virtual environment

**Windows (PowerShell)**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```
If PowerShell blocks the script, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, or use
`.\.venv\Scripts\activate.bat` from `cmd`.

**macOS / Linux**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. (Optional) Configure environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `SECRET_KEY` | random on each start | Signs the session cookie. Set it to keep users logged in across restarts. |
| `DATABASE_URL` | `sqlite:///./coffee_shop.db` | Database location |
| `ADMIN_USERNAME` | `admin` | Username of the first admin, created if no admin exists |
| `ADMIN_PASSWORD` | `admin12345` | Password of the first admin |
| `SEED_DEMO_DATA` | `true` | Seed demo products and the demo `staff` and `loyal` accounts |

PowerShell example:
```powershell
$env:SECRET_KEY = "change-me-to-a-long-random-string"
```
Bash example:
```bash
export SECRET_KEY="change-me-to-a-long-random-string"
```

### 4. Start the server

```bash
uvicorn main:app --reload
```
(or `python main.py`)

Open **http://127.0.0.1:8000** in your browser.

On the first start the app creates `coffee_shop.db`, the tables, the loyalty discount rule (20% over €20),
an admin account and, unless disabled, demo data.

### Demo accounts

| Role | Username | Password |
|------|----------|----------|
| Admin | `admin` | `admin12345` |
| Staff | `staff` | `staff12345` |
| Loyalty | `loyal` | `loyal12345` |

Change these credentials, or set `SEED_DEMO_DATA=false` and `ADMIN_PASSWORD`, before using the app anywhere other than your own machine.

### Useful URLs

| URL | Description |
|-----|-------------|
| `/` | Home page with the menu |
| `/products` | Full menu with filter |
| `/cart` | Shopping cart |
| `/cart/checkout` | Checkout (pickup/delivery + Pay Now) |
| `/orders/my` | Order history (logged-in users) |
| `/orders/dashboard` | Fulfilment dashboard (staff/admin) |
| `/admin` | Admin dashboard |
| `/products/api` | Menu as JSON |
| `/docs` | Auto-generated OpenAPI docs |

### Resetting the application

Stop the server, delete `coffee_shop.db` (and any uploaded files in `static/images/` except the
`placeholder-*.svg` files), then start it again.

## Known limitations of the v0 baseline

These are left out on purpose and are the starting point for the security phase of the project:

- No CSRF protection on forms
- No rate limiting or account lockout on login
- No security headers (CSP, HSTS, X-Frame-Options, …)
- The session cookie is not marked `Secure` (the app runs over plain HTTP locally)
- Uploaded images are checked by file extension and size only, not by content
- No audit logging
- Payment is simulated
