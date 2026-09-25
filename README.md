# BLOCK ERP

A real-estate project costing, flat sales, receivables, payables and profitability ERP for a small
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
- `customers` — contact master data, identified by a unique phone number (no separate customer code); create/update only, no delete
- `suppliers` — contact master data with an auto-generated code; create/update only, no delete
- `projects` — `Project` (one building = one project) and `Flat` (floor, type, facing, area, price). Flat status is automatic: Available (no active sale), Booked (sold to a customer, payment pending), Sold (fully paid)
- `costing` — `CostCategory` tree, `ProjectBudget`, `ProjectCost`, and the area-based `CostAllocation` engine. Costs are entered on two separate forms: *Shared* (whole building, allocated across all flats by area) and *Direct* (one flat only)
- `sales` — `FlatSale` and `CustomerPayment` (drives received/receivable)
- `payables` — `SupplierPayment` (drives paid/payable on `ProjectCost`; a payment can't exceed the cost's remaining payable amount)
- `books` — independent Cash Book / Bank Book / Bank Accounts ledger
- `reports` — project profitability, flat-wise, and receivable/payable reports (+ PDF export)
- `dashboard` — home page with company-wide quick stats
- `activity_log` — explicit create/update/delete audit trail shown on the dashboard

## Numbering

- Project codes have no year component: `{COMPANY_CODE_PREFIX}P-{NNN}`, e.g. `ABP-001`.
- Supplier codes also have no year component, dash-separated: `{COMPANY_CODE_PREFIX}-S-{NNN}`, e.g. `AB-S-001`.
- Customers have no code at all — they're identified by name + a unique phone number.
- Sale numbers use `{PREFIX}/{YYYY}/{NNNNN}`, e.g. `AB/2026/00001`.

All of these are minted atomically via `core.numbering` (`select_for_update` on a `Sequence` row), not a
racy `count()+1`.
