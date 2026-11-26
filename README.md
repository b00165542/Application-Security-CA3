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

### 3. Configure environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `SECRET_KEY` | random on each start | Signs the session cookie. Set it to keep users logged in across restarts. |
| `DATABASE_URL` | `sqlite:///./coffee_shop.db` | Database location |
| `ADMIN_USERNAME` | **required on first start** | Username of the first admin, created if no admin exists (3–32 chars: letters, digits, `_ . -`) |
| `ADMIN_PASSWORD` | **required on first start** | Password of the first admin (8–72 chars) |
| `SEED_DEMO_DATA` | `true` | Seed demo products and the demo staff and loyalty accounts |
| `DEMO_STAFF_USERNAME` | **required while `SEED_DEMO_DATA` is on** | Username of the demo staff account |
| `DEMO_STAFF_PASSWORD` | **required while `SEED_DEMO_DATA` is on** | Password of the demo staff account (8–72 chars) |
| `DEMO_LOYALTY_USERNAME` | **required while `SEED_DEMO_DATA` is on** | Username of the demo loyalty account |
| `DEMO_LOYALTY_PASSWORD` | **required while `SEED_DEMO_DATA` is on** | Password of the demo loyalty account (8–72 chars) |

There are no default accounts or passwords. All usernames and passwords follow the registration rules
(username 3–32 chars: letters, digits, `_ . -`; password 8–72 chars), and each username must be unique.
If a required value is missing, invalid, or clashes with another account, the app refuses to start and
logs the reason, for example:

```
CRITICAL:coffee_shop:Startup aborted: ADMIN_PASSWORD is not set. Set ADMIN_USERNAME and ADMIN_PASSWORD to create the first admin account (none exists yet), then restart the app.
CRITICAL:coffee_shop:Startup aborted: DEMO_STAFF_USERNAME and DEMO_STAFF_PASSWORD are not set. Set DEMO_STAFF_USERNAME and DEMO_STAFF_PASSWORD to create the demo staff account, or set SEED_DEMO_DATA=false, then restart the app.
```

- The `ADMIN_*` variables are only needed until the first admin exists.
- The `DEMO_*` variables are needed on every start while `SEED_DEMO_DATA` is on. A demo account that
  already exists is left unchanged, so changing `DEMO_*_PASSWORD` later does not reset its password.
- To run without demo accounts or products, set `SEED_DEMO_DATA=false`; the `DEMO_*` variables are then ignored.

#### Set them with a `.env` file (recommended)

1. Copy the template. [`.env.example`](.env.example) is committed; your `.env` is git-ignored and must never be committed.

   ```powershell
   Copy-Item .env.example .env     # PowerShell
   ```
   ```bash
   cp .env.example .env            # Bash
   ```

2. Open `.env` and replace **every** placeholder value (`SECRET_KEY`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`, ...)
   with your own. Do not start the app with the placeholders left in: they are valid values, so they would
   become the real usernames and passwords. To generate a `SECRET_KEY`:

   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

3. If you previously ran the app with the old built-in accounts, delete `coffee_shop.db` so the accounts are
   recreated from your new values. Existing accounts are never updated from the environment.

The app does not read `.env` by itself. Uvicorn loads it with the `--env-file` option (see step 4), using
`python-dotenv`, which is installed with `uvicorn[standard]`.

#### Alternative: set them in the current shell

Variables set this way only last for the current terminal session.

```powershell
$env:ADMIN_USERNAME = "your-admin-name"     # PowerShell; repeat for each variable
```
```bash
export ADMIN_USERNAME="your-admin-name"     # Bash; repeat for each variable
```

### 4. Start the server

With a `.env` file:

```bash
uvicorn main:app --reload --env-file .env
```

With variables already set in the shell:

```bash
uvicorn main:app --reload
```

`python main.py` also works, but only with variables set in the shell, because it does not load `.env`.

Open **http://127.0.0.1:8000** in your browser.

On the first start the app creates `coffee_shop.db`, the tables, the loyalty discount rule (20% over €20),
an admin account and, unless disabled, demo data.

### Demo accounts

| Role | Username | Password |
|------|----------|----------|
| Admin | value of `ADMIN_USERNAME` | value of `ADMIN_PASSWORD` |
| Staff | value of `DEMO_STAFF_USERNAME` | value of `DEMO_STAFF_PASSWORD` |
| Loyalty | value of `DEMO_LOYALTY_USERNAME` | value of `DEMO_LOYALTY_PASSWORD` |

Set `SEED_DEMO_DATA=false` before using the app anywhere other than your own machine, so the demo staff and loyalty accounts are not created.

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
