# BLOCK ERP

A real-estate project costing, flat sales, receivables and profitability ERP for a small
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

For a demo database, run `venv\Scripts\python manage.py seed_demo_data` on a fresh database (Tower 1 and Tower 2 with 12 floors
x 4 flats each, 4 customers, 6 bookings with initial payments, and 15,000,000 of costs). It refuses to run if data already exists.

Visit http://localhost:8010/, log in, and the dashboard links to every module.

## App layout

- `core` — atomic numbering (`Sequence` + `core.numbering`), shared audit-log mixins, `taka` template filter
- `customers` — contact master data, identified by a unique phone number (no separate customer code); create/update only, no delete
- `suppliers` — contact master data with an auto-generated code; create/update only, no delete
- `projects` — `Project` (one building = one project) and `Flat` (floor, type, facing, area, price). Flat status is automatic: Available (no active sale), Booked (sold to a customer, payment pending), Sold (fully paid)
- `costing` — `CostCategory` tree, `ProjectBudget`, `ProjectCost`, and the area-based `CostAllocation` engine. Every cost entry counts as paid — there is no payable tracking. Costs are entered on two separate forms: *Shared* (whole building, allocated across all flats by area) and *Direct* (one flat only)
- `sales` — `FlatSale` and `CustomerPayment` (drives received/receivable)
- `books` — independent Cash Book / Bank Book / Bank Accounts ledger
- `reports` — project profitability, flat-wise, and receivables reports (+ PDF export)
- `dashboard` — home page with company-wide quick stats
- `activity_log` — explicit create/update/delete audit trail shown on the dashboard

## Printing

Print-ready A4 pages (use the browser's Print, or "Save as PDF"), each with a company header, amount in words and signature lines:

- **Payment voucher** for a cost: `Print Voucher` on the cost page and the print icon in the cost list (`CV-00001`)
- **Invoice** for a flat sale: `Print Invoice` on the sale page (numbered with the sale number)
- **Money receipt** for a customer payment: print icon in the sale's payments and in the payments list (`MR-00001`);
  it shows the balance as of that payment

- **Project cost report (PDF)**: "Print PDF of this list" on the cost list exports whatever the list is currently filtered to
  (search, project, shared/direct, month or date range), with a total and a summary by cost head

**Letterhead:** upload your company letterhead under *your name menu → Company Letterhead* (PNG or JPG, max 5 MB;
a wide banner around 2480 x 400 px prints at full A4 width). It is used at the top of every voucher, invoice,
receipt and PDF report in place of the text heading. With no letterhead, the printed heading uses the company name,
address and phone from the same page, falling back to `COMPANY_NAME`, `COMPANY_ADDRESS` and `COMPANY_PHONE` in `.env`.
Uploads are stored in `media/letterhead/`; in production make sure the web server serves `MEDIA_URL` from `MEDIA_ROOT`.
Only users with the `core.change_companyprofile` permission (superusers) see and can use this page.

## Numbering

- Project codes have no year component: `{COMPANY_CODE_PREFIX}P-{NNN}`, e.g. `ABP-001`.
- Supplier codes also have no year component, dash-separated: `{COMPANY_CODE_PREFIX}-S-{NNN}`, e.g. `AB-S-001`.
- Customers have no code at all — they're identified by name + a unique phone number.
- Sale numbers use `{PREFIX}/{YYYY}/{NNNNN}`, e.g. `AB/2026/00001`.

All of these are minted atomically via `core.numbering` (`select_for_update` on a `Sequence` row), not a
racy `count()+1`.
