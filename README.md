# BLOCK ERP

A real-estate project costing, apartment sales, receivables, payables and profitability ERP for a small
apartment-development company, built to match the UI/UX of the sister "Inspecta ERP" (inspcta) codebase.

## Stack

- Django 4.2.20, Python 3
- SQLite for local dev; MySQL/Postgres in production via `DATABASE_URL` in `.env`
- Bootstrap 5 + Font Awesome (CDN), django-crispy-forms with crispy-bootstrap5
- reportlab for PDF report export

## Setup

```bash
python -m venv venv
venv\Scripts\pip install -r requirements.txt
venv\Scripts\python manage.py migrate
venv\Scripts\python manage.py seed_cost_categories
venv\Scripts\python manage.py createsuperuser
venv\Scripts\python manage.py runserver 8010
```

Visit http://localhost:8010/, log in, and the dashboard links to every module.

## App layout

- `core` — atomic numbering (`Sequence` + `core.numbering`), shared audit-log mixins, `taka` template filter
- `customers`, `suppliers` — contact master data with auto-generated codes
- `projects` — `Project` (one building = one project) and `Apartment`
- `costing` — `CostCategory` tree, `ProjectBudget`, `ProjectCost`, and the area-based `CostAllocation` engine
- `sales` — `ApartmentSale` and `CustomerPayment` (drives received/receivable)
- `payables` — `SupplierPayment` (drives paid/payable on `ProjectCost`)
- `books` — independent Cash Book / Bank Book / Bank Accounts ledger
- `reports` — project profitability, apartment-wise, and receivable/payable reports (+ PDF export)
- `dashboard` — home page with company-wide quick stats
- `activity_log` — explicit create/update/delete audit trail shown on the dashboard

## Numbering

Codes follow `{YY}{COMPANY_CODE_PREFIX}{TYPE}{NNNN}`, e.g. project `26ABP0001`, customer `26ABC0001`,
supplier `26ABS0001`; sale numbers use `{PREFIX}/{YYYY}/{NNNNN}`, e.g. `AB/2026/00001`. Numbers are
minted atomically via `core.numbering` (`select_for_update` on a `Sequence` row), not a racy `count()+1`.
