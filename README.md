# DAR AL JANNAH ERP

A real-estate ERP for a company that sells **flat shares before development** and then builds the project, with
**post-development costs shared equally by the owners of every flat**. Powered by NOORSYS. It follows the UI/UX of the
sister "Inspecta ERP" (inspcta) codebase.

## Stack

- Django 4.2.20, Python 3
- SQLite for local dev; another database via `DATABASE_URL` in `.env`
- Bootstrap 5 + Font Awesome (CDN), django-crispy-forms with crispy-bootstrap5
- reportlab for PDF export, openpyxl for Excel export

## Setup

```bash
python -m venv venv
venv\Scripts\pip install -r requirements.txt
copy .env.example .env
venv\Scripts\python manage.py migrate
venv\Scripts\python manage.py seed_cost_categories
venv\Scripts\python manage.py createsuperuser
venv\Scripts\python manage.py runserver 8010
```

For a demo database, run `venv\Scripts\python manage.py seed_demo_data` on a fresh database (Tower 1 and Tower 2, 12 floors
x 4 flats each, 3 accounts, 4 customers, 6 bookings with initial payments, a reference, and 15,000,000 of costs). It refuses
to run if data already exists.

### Upgrading an existing database

`python manage.py migrate` keeps your data: numeric flat numbers (`101`) become unit + floor (`A1`) where that is
unambiguous, the first flat's type/size/price moves up to the project, existing sales keep their value as the new
*sale value*, costs get their phase from their category, and customer/supplier phone numbers get `+88`. Two things
need a look afterwards:

- **Payments and costs made before accounts existed have no bank/cash account.** They are not in any balance until you
  open each record's account (the Books page lists them under "No account yet").
- The hand-typed Cash Book and Bank Book are gone (the book is now collected automatically). Their rows are written to
  `backups/old_cash_and_bank_book_<time>.csv` during the migration. Keep a copy of your database before upgrading.

## How the money works

**Pre-development (before construction).** The company sells flat *shares* at a base price.

| | |
|---|---|
| Base price | what the company needs per flat share (set once on the project) |
| Parking | optional; its price is added to the base price when the buyer takes the parking lot |
| Total base price | base price + parking price |
| Sale value | what the buyer agrees to pay, never below the total base price |
| **Honorarium** | sale value − total base price, paid to the reference (the "Ref") |
| Reg value | registration cost, borne by the customer |
| Net value | sale value + reg value: everything the customer owes |

A flat is **Sold** as soon as a sale is saved (there is no separate "Booked" status), and **Available** again if the sale is
cancelled. Paying more than the net value is kept as the **customer balance**. Cancelling a booking returns a **refund percentage** of everything received (it can
be below 100%); the company keeps the rest. Pre-development profit = base price earned from share sales (+ money kept on
cancellations) − land, marketing and pre-development administrative costs.

**Post-development (after construction starts).** All costs are borne **equally by the owners of every flat, sold or not**
(per flat, not by area). The cost screens, books and reports keep the two phases apart.

| Cost category | Phase |
|---|---|
| Land, Marketing | Pre-development |
| Administration | Either: chosen on each entry |
| Everything else | Post-development |

A cost recorded against a single flat (a *direct* cost) is always post-development and is added to that flat only.

## The book

Bank 1, Bank 2, Petty cash ... are **accounts** (Books → Accounts). **Nothing is typed into the book**: every line is
collected from where the money was first recorded, so nothing is entered twice.

- customer payments (money in), refunds, honorarium payments and cost payments (money out)
- internal transfers between your own accounts (Books → Internal Transfers)

Each payment/cost screen asks which account the money moved through. A new line does **not** appear in the book yet:

1. It waits on **Books → Confirm entries** (one account at a time). Someone with the *Can confirm book entries*
   permission checks it against the paper record, ticks it and confirms.
2. Only **confirmed** entries appear in the book. **A confirmation is final: it cannot be undone**, and a confirmed
   cost can no longer be edited or deleted.
3. **An account's balance can never go below zero.** A confirmation that would take it below zero, at any date, is
   refused with a message; confirm the money coming in first.

The book shows **one account at a time** (tabs along the top) for a date range, with opening and closing balance, and
downloads as **Excel**. Records made before accounts existed have no account: give them one at the bottom of the
Confirm entries page, then confirm them.

## Flats and the booking map

All flats in a project are identical, so type, area, rooms and prices are set **once on the project**. Flats are numbered
**unit letter + floor** (A1 = unit A, floor 1) and each has a linked parking lot (default `P-A1`). *Generate flats*
creates every unit on every floor in one step. The project page has a bus-seat style **booking map** (free / sold,
parking lot and customer on each seat); click a free flat to book it.

The all-flats list shows **one project at a time**. Flats cannot be deleted directly. An admin (superuser, or a user with `projects.delete_flat`) **requests** the deletion with
a reason and a *different* admin **approves** it (Projects → Flat deletion requests). A flat with sales or direct costs can
never be deleted.

## Sensitive screens (password re-entry)

The software is shown to buyers but also records money, so Costing, Books and Reports ask the signed-in user to type
their password again. It stays unlocked while they keep working and locks after `REAUTH_MINUTES` of inactivity, when the
browser is closed, or via the user menu → *Lock sensitive screens*. While locked, the money figures stay hidden everywhere
else too: costs, sale value, received, receivable, honorarium, the base price and payment amounts on the home, project,
flat, sales, payment and customer pages. Change which areas are guarded with `SENSITIVE_NAMESPACES` in `.env`.

## Customer SMS

- An SMS is sent on **every payment received** (receipt number, amount, balance).
- **Balance reminders** are only sent when a user does it: Sales → Balance reminders → tick customers → Send.
- Tick **Send SMS** off on a customer to exclude them from everything.
- Every message is recorded in Sales → SMS log.

`SMS_BACKEND=log` (the default) only records messages in the SMS log. `SMS_BACKEND=zendsms` sends them for real through
[ZendSMS](https://api.zendsms.com) using `SMS_API_KEY` and `SMS_SENDER_ID` (plus `SMS_API_URL` / `SMS_BALANCE_URL`, which
default to ZendSMS's addresses). Put the API key in `.env` only, never in `.env.example` or in git.
Sales → SMS log → **Check SMS balance** asks ZendSMS what is left, and every log line shows the gateway's message id or
the reason it refused. A gateway failure never stops a payment from saving. The request format follows ZendSMS's Laravel
package (their HTTP docs are not public): confirm one real send after switching on `zendsms`.

## Invoices on WhatsApp

Sales → **Send invoices on WhatsApp** lists every customer with a **WhatsApp number** and an active sale (customers
without one are listed separately with an "Add WhatsApp no." link). **Send** opens WhatsApp (app or web) with the
customer's number and the message already typed; you press send there. The sale page has the same **Send on WhatsApp**
button. Each time WhatsApp is opened it is recorded.

WhatsApp cannot attach a file from a link, so the message carries a **private link to the invoice page** that the customer
can open, view and print with no password. The link is signed, so it cannot be guessed or changed, and it stops working after
30 days. The page shows only the customer-facing invoice (never the base price or honorarium). Set `SITE_URL` in `.env`
(for example `https://erp.example.com`) so the link always has the right address behind a hosting proxy.

Sending automatically from the server (no click) needs the WhatsApp Business Cloud API, which means a Meta business account and
approved message templates. This version does not use it.

## Reports (Reports menu, PDF and Excel buttons on each)

- **Finance report** (all phases): sales, cost, receivable, payable and money in hand
- **Periodic payment collection** (pre-development): by month, customer and account, for any period
- **Profit, loss, collection and due** (pre-development)
- **Customer balance, cost, receivable and payable** (post-development)
- Flat-wise report and Receivables

The book and the project cost list download as Excel too (real numbers and dates, not text). The dashboard shows quick cost statistics (pre/post/total, per-flat share, this month, biggest heads) once unlocked.

## Configuration (`.env`)

Settings that differ per server live in a `.env` file next to `manage.py`, not in the code. Copy `.env.example` to `.env`
(it documents every setting) and edit it on each machine; `.env` is git-ignored so a server keeps its own. Restart the
app after changing it. Real environment variables set by the hosting panel override the file.

On a hosting server the ones to set are:

```
DEBUG=False
SECRET_KEY='a-long-random-string'
ALLOWED_HOSTS=erp.example.com,www.example.com
COMPANY_NAME=DAR AL JANNAH
```

`ALLOWED_HOSTS` is a comma-separated list of bare domain names (no `https://`, no trailing `/`; a leading dot such as
`.example.com` also allows subdomains). Visitors using any other name see "Bad Request (400)". A pasted URL stops the app
with a message naming the bad entry.

## App layout

- `core` — atomic numbering, audit-log mixins, `taka` filter, password re-entry (`core.reauth`), `+88` phone normalising
- `customers` — title, phones (`+88` added automatically), WhatsApp, emergency contact, TIN, SMS opt-out; unique phone, no delete
- `suppliers` — company, owner, contact, bank account and a *type* (the cost categories); no delete
- `projects` — `Project` (flat spec and prices set once), `Flat` (unit + floor, parking lot), booking map, two-admin flat deletion
- `costing` — categories with phases, budgets, project costs (shared / direct, "paid from" account)
- `sales` — `FlatSale`, `CustomerPayment`, `Reference`, `HonorariumPayment`, `RefundPayment`
- `books` — accounts, internal transfers and the collected book with its confirmation layer
- `sms` — payment SMS, balance reminders, SMS log
- `reports` — the reports above, shown on screen and as letterhead PDFs
- `dashboard` — home page with quick stats
- `activity_log` — create/update/delete audit trail

## Printing

Print-ready A4 pages (use the browser's Print, or "Save as PDF"), each with a company header, amount in words and signature lines:

- **Payment voucher** for a cost (`CV-00001`), showing phase and the account it was paid from
- **Invoice** for a flat sale. It is given to the buyer, so it shows only the sale value, reg value, net value and payments, never the base price or honorarium
- **Money receipt** for a customer payment (`MR-00001`); it shows the balance as of that payment
- **Project cost report (PDF)** from the cost list, honouring the list's filters (search, project, type, phase, month or dates)

**Letterhead:** upload your company letterhead under *your name menu → Company Letterhead* (PNG or JPG, max 5 MB;
a wide banner around 2480 x 400 px prints at full A4 width). It is used at the top of every voucher, invoice,
receipt and PDF report in place of the text heading. With no letterhead, the printed heading uses the company name,
address and phone from the same page, falling back to `COMPANY_NAME`, `COMPANY_ADDRESS` and `COMPANY_PHONE` in `.env`.
Uploads are stored in `media/letterhead/`; in production make sure the web server serves `MEDIA_URL` from `MEDIA_ROOT`.

## Numbering

- Project codes: `{COMPANY_CODE_PREFIX}P-{NNN}`, e.g. `ABP-001`. Supplier codes: `{COMPANY_CODE_PREFIX}-S-{NNN}`, e.g. `AB-S-001`.
- Customers have no code; they are identified by name + a unique phone number.
- Sale numbers: `{PREFIX}/{YYYY}/{NNNNN}`; receipts `MR-`, vouchers `CV-`, honorarium `HP-`, refunds `RF-`, transfers `TR-`.

All of these are minted atomically via `core.numbering` (`select_for_update` on a `Sequence` row), not a racy `count()+1`.

## Tests

```bash
venv\Scripts\python manage.py test
```
