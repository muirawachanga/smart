# Development setup

This repository contains a custom Frappe app. The Frappe framework and MariaDB
are managed by a Frappe Bench installation; this repository is installed as an
app inside that bench. The project proposal remains in the root `README.md`.
The website product name is SmartO. The internal Frappe app, Python package,
and DocType module remain `intelligent_ordering` / `Intelligent Ordering` to
preserve existing identifiers and database compatibility.

## Prerequisites

- A supported Frappe Bench environment with Python, Node.js, Redis, and MariaDB.
- A site created by Bench.
- Git.

Frappe versions are intentionally not pinned here. Select and record the
framework/Bench version for the deployment environment before creating the
site, and use that same version for development and evaluation.

## Install the app

From the bench directory:

```bash
bench get-app intelligent_ordering <repository-url>
bench --site <site-name> install-app intelligent_ordering
bench --site <site-name> migrate
bench start
```

For a local repository checkout, link it into the bench and install it in the
bench environment:

```bash
ln -s /absolute/path/to/smart apps/intelligent_ordering
./env/bin/pip install -e apps/intelligent_ordering
bench --site <site-name> install-app intelligent_ordering
```

Open the site URL printed by `bench start`. The SmartO homepage is available
at `/`, and the existing database-backed catalog and operations are at
`/store`. Frappe's login and session handling provide the authentication
foundation. Assign the app roles to test users from the Frappe Desk.

## SmartO website routes

The public website uses native Frappe `www` routes and a shared Jinja layout;
it does not add a JavaScript framework. The shared layout provides the SmartO
header, responsive navigation, breadcrumbs, account links, footer, and
route-aware page labels.

| Route | Current Phase 2 page |
| --- | --- |
| `/` | SmartO homepage |
| `/about` | About SmartO |
| `/products` | Searchable, filterable, sortable product catalogue |
| `/products/<product_id>` | Database-backed product details |
| `/product-details?product=<product_id>` | Product details for identifiers that cannot be used as a path segment |
| `/categories` | Enabled product categories |
| `/cart` | Cart page shell |
| `/checkout` | Checkout page shell |
| `/payment` | Payment page shell |
| `/order-confirmation/<order_id>` | Order confirmation shell using a Frappe route rule |
| `/track-order` | Tracking page shell |
| `/contact` | Contact page shell; business contact data is not configured |
| `/login` | Frappe's native login page; it is not replaced |
| `/register` | Registration information page; account creation is not implemented here |
| `/forgot-password` | Password recovery information page |
| `/reset-password` | Password reset information page; it accepts no credentials or tokens |
| `/account` | Customer account page shell |
| `/dashboard/owner` | Business owner dashboard shell |
| `/dashboard/admin` | Administrator dashboard shell |
| `/dashboard/sales` | Sales dashboard shell |
| `/dashboard/orders` | Order dashboard shell |
| `/dashboard/inventory` | Inventory dashboard shell |
| `/dashboard/delivery` | Delivery dashboard shell |
| `/store` | Existing database-backed storefront and staff workflows |

Unconnected page shells deliberately do not invent customer data, accept payment
details, create accounts, or submit orders. Existing cart, checkout,
order, payment, inventory, delivery, and administration workflows remain
available at `/store` until the later page-specific phases connect them. The
dashboard shells contain no operational data; their role-specific data and
server-side access controls will be connected with personnel dashboards.
Frappe's native `/login` remains the authentication authority.

After changing website templates, route rules, or public assets, rebuild app
assets and restart the Bench site:

```bash
bench build --app intelligent_ordering
bench restart
```

## Configuration and secrets

Copy `.env.example` only as a reference for the external credentials that
future integrations may require. Frappe does not load it automatically.
Configure database/site settings using Bench and store provider secrets in
the site's `site_config.json` or the deployment secret manager. Do not commit
credentials or production site configuration.

The current scaffold does not call external AI, payment, SMS, or mapping
services. Use provider sandbox credentials only when those integrations are
implemented.

## Tests and checks

Run the standalone validation tests from the repository root:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e .
python -m unittest discover -s tests -v
node --test tests/frontend/*.test.js
```

Run app tests from the bench directory after installing the app on a test
site:

```bash
bench --site <test-site-name> run-tests --app intelligent_ordering
```

Apply DocType changes to a site with:

```bash
bench --site <site-name> migrate
```

## Catalog API

Frappe exposes the starter methods through its standard method API:

- `GET /api/method/intelligent_ordering.api.v1.ping`
- `GET /api/method/intelligent_ordering.api.v1.current_user`
- `GET /api/method/intelligent_ordering.api.catalog.get_catalog`
- `GET /api/method/intelligent_ordering.api.catalog.get_product`

The catalog endpoint supports `search`, `category`, `page`, `page_size`, and `sort`
query parameters. It returns enabled products and enabled categories from the
site database; disabled categories and products are not shown. Search covers
product name, SKU, and description. Allowed sort values are `name_asc` (default),
`name_desc`, `price_asc`, and `price_desc`. Price sorting compares numeric
amounts without currency conversion. Results are paginated, with a maximum page
size of 100. The detail endpoint accepts `product` and applies the same
visibility rules. Catalog responses include current
available stock and an In Stock/Out of Stock label. Product management is
available to authorized staff through Frappe Desk DocTypes.

`ping` returns a minimal service status. `current_user` requires an
authenticated Frappe session and returns the signed-in user's name and roles.
The catalog does not calculate cart totals or reserve stock.
The homepage shows the first four products by name, not a curated featured
selection. Product listing and detail pages add to the existing guest or
customer cart; cart review and checkout remain at `/store` for now.

## Shopping cart API

Cart methods are POST-only:

- `POST /api/method/intelligent_ordering.api.cart.get_cart`
- `POST /api/method/intelligent_ordering.api.cart.add_item`
- `POST /api/method/intelligent_ordering.api.cart.update_item`
- `POST /api/method/intelligent_ordering.api.cart.remove_item`
- `POST /api/method/intelligent_ordering.api.cart.clear_cart`
- `POST /api/method/intelligent_ordering.api.cart.merge_guest_cart`

Authenticated customers have one database-persisted cart per Frappe user.
Guests have a browser-local cart; the server validates product identifiers,
quantities, enabled status, prices, and totals on every operation. A guest cart
is merged into the signed-in user's cart on first load after authentication.
Prices are always read from Product records; submitted prices are ignored.
Products with disabled records or disabled categories cannot be added.
Active warehouse availability is shown in the catalog and checked when a
product is added to a cart. Final stock reservation happens only when an order
is confirmed.

The storefront includes cart quantity controls, removal and clear actions,
subtotals, and totals. Guest carts are merged after sign-in; checkout requires
an authenticated Customer role.

## Checkout and order management

Checkout and order methods are available through Frappe's standard method API:

- `GET /api/method/intelligent_ordering.api.checkout.get_checkout`
- `POST /api/method/intelligent_ordering.api.checkout.create_order`
- `GET /api/method/intelligent_ordering.api.orders.get_my_orders`
- `GET /api/method/intelligent_ordering.api.orders.get_order`
- `GET /api/method/intelligent_ordering.api.orders.list_orders`
- `POST /api/method/intelligent_ordering.api.orders.update_order_status`

Checkout returns the current server cart and a revision for the customer to
review. Order creation requires the revision, a unique request token, customer
contact information, and a delivery address. Product prices and totals are
re-read and calculated from Product records; browser-submitted prices and
totals are not accepted. The cart is cleared only after the Sales Order has
been inserted successfully. Repeating a request token for the same customer
returns the existing order.

Customers can list and view only their own orders. Business Admin and Order
Manager roles can search, filter, inspect, and update order statuses. Submitted
order details and line prices are immutable; status changes are validated on
the server with these transitions: Pending → Confirmed → Processing → Ready
for Delivery → Completed, with cancellation permitted before completion.
Completed and Cancelled are terminal. Legacy Sales Order statuses are not
automatically remapped; an explicit migration is required before rollout if
legacy records exist.

The storefront provides checkout review, order confirmation, customer order
history, and staff order search/status controls. M-Pesa is an optional,
server-configured integration. New orders include the configured delivery-area
fee in their immutable server-calculated total. Product/category-at-order
snapshots support historical reporting; old orders without a snapshot report
as uncategorized rather than being silently reclassified.

## Inventory management

Inventory methods:

- `GET /api/method/intelligent_ordering.api.inventory.get_dashboard`
- `GET /api/method/intelligent_ordering.api.inventory.list_stock`
- `GET /api/method/intelligent_ordering.api.inventory.list_movements`
- `GET /api/method/intelligent_ordering.api.inventory.get_product_availability`
- `POST /api/method/intelligent_ordering.api.inventory.adjust_stock`
- `POST /api/method/intelligent_ordering.api.inventory.record_order_return`

Stock Warehouse records are managed by authorized staff in Desk. Stock Balance
tracks on-hand, reserved, and available units for each product/warehouse pair.
Opening stock can be recorded once per pair; receipts increase stock and
adjustments accept a signed whole-number quantity. Balances cannot be negative
or reduced below reserved quantities. Stock Ledger Entry is append-only and
records each movement, order reference, transaction time, and responsible
user. Existing Inventory Location records and legacy ledger fields are kept
without changing their history.

Order confirmation reserves available stock across active warehouses in
warehouse-name order. If stock is insufficient, the status change fails and
the order remains Pending. Ready for Delivery converts reservations into a
dispatch movement and reduces on-hand stock. Cancellation before dispatch
releases reservations. After dispatch, authorized inventory staff must record
returns before the order can be cancelled. Stock operations run inside the
order update transaction, lock product rows during allocation, and use unique
movement keys to avoid duplicate reservations or dispatches. Orders remain
Pending without affecting inventory until confirmation. Inventory screens
provide dashboard totals, product/warehouse stock search, movements, and
authorized receipt/adjustment controls.

## M-Pesa configuration and operations

Configure a nested `mpesa` object in the site's private `site_config.json` using
Bench or your deployment secret manager. `.env.example` is reference only.
Do not put real credentials in source control, JavaScript, or support tickets.

```json
{
  "mpesa": {
    "environment": "Sandbox",
    "consumer_key": "<Daraja app consumer key>",
    "consumer_secret": "<Daraja app consumer secret>",
    "shortcode": "<business shortcode>",
    "passkey": "<STK passkey>",
    "transaction_type": "CustomerPayBillOnline",
    "callback_url": "https://your-public-host/api/method/intelligent_ordering.api.payments.callback",
    "payment_expiry_minutes": 0
  }
}
```

Use the matching Daraja application's Sandbox credentials and test phone
before switching to `Production` with approved live credentials. Paybill and
Buy Goods transaction types are supported; select the type approved for your
shortcode. Never switch environments/shortcodes while attempts remain
unresolved. Keep test and live sites separate. Apply DocTypes with
`bench --site <site> migrate` and restart workers after deployment.
Set the site's system timezone to `Africa/Nairobi` for Daraja transaction dates.

Every attempt generates a random callback bearer token; only its SHA-256 hash
is stored. The callback URL sent to Daraja includes the token. Treat callback
URLs as credentials: redact query strings in reverse-proxy/access/error logs,
disable caching on payment endpoints, and do not forward callback requests to
analytics. Enforce HTTPS, site request rate limits, and a 16 KB callback body
limit at the reverse proxy. Keep the public callback reachable without browser
authentication. Do not disable CSRF protection globally: browser mutations use
Frappe session/CSRF protection; Daraja must POST without a browser session.

Payment endpoints use the prefix
`/api/method/intelligent_ordering.api.payments.`:

| Method | Endpoint | Access |
| --- | --- | --- |
| POST | `initiate_payment(order_name, phone)` | Order owner |
| POST | `callback` | Per-attempt callback token, plus server Daraja verification |
| GET | `get_order_payments(order_name)` | Order owner, redacted transaction fields |
| GET | `list_transactions(search, status, page, page_size)` | Payment staff |
| GET | `get_transaction(payment_name)` | Payment staff |
| GET | `payment_summary` | Payment staff, grouped by environment/status |
| POST | `reconcile_payment(payment_name)` | Payment staff, authenticated STK status query |
| POST | `expire_unpaid_order(order_name)` | Staff-only configured expiry/cancellation |

Payment staff are Business Admin, Store Manager, Order Manager, Finance
Manager, and System Manager. They can
inspect raw callback/query records but cannot edit statuses through generic
DocType writes. Receipt and checkout IDs are unique. There is no browser
"confirm payment" API and no PIN collection. Reversed is reserved in the schema;
this module does not initiate reversals or manufacture reversal confirmations.

Only positive whole KES order totals up to KES 250,000 are accepted; fractional
totals are rejected, never rounded into a different charge. The customer may
use a different valid Kenyan M-Pesa mobile number from their delivery contact.
The server stores that number and verifies callback amount, number, request
IDs, receipt format and date, plus an independent OAuth-authenticated STK query.
Query success alone lacks amount/receipt metadata and therefore cannot mark
an order paid without a matching token-authenticated success callback.

STK attempts are committed before the external call, under an order lock.
Repeated clicks return the active attempt rather than initiating another
charge. A timeout or ambiguous provider response stays unresolved; it is not
treated as a failed payment. Explicit provider initiation rejections and
definitive query failures allow a new attempt.
Callbacks and reconciliation serialize on the order/payment locks; repeated
successes do not write inventory or repeat payment processing. A late verified
payment on a cancelled order is recorded as paid without reopening the order;
staff must resolve it with the customer outside this module.

Successful payment marks only `payment_status = Paid`. Staff still confirm
orders and inventory still reserves on confirmation and dispatches at Ready
for Delivery. Unpaid orders cannot be completed. Failed attempts do not change
the order or automatically release reservations. Cancellation remains a staff
action through existing order status rules. Expiry is disabled (`0`) by
default; an administrator may set a positive integer `payment_expiry_minutes`,
after which staff can explicitly call `expire_unpaid_order` for an unpaid,
undispatched order. That action uses normal cancellation/reservation release.
No automatic cancellation job is installed.

### Sandbox verification before rollout

The standalone tests mock HTTP, OAuth, callbacks, and status queries; they do
not constitute a real Daraja Sandbox result. The Frappe payment tests mock
Daraja but exercise database persistence and permissions on a test Bench site.
With Sandbox credentials and a reachable HTTPS callback, create an order,
initiate STK Push, complete/cancel the prompt, verify the recorded amount and
receipt, replay the callback, and reconcile from the Payments dashboard.
Confirm the order stays Pending after payment, staff confirmation reserves
stock once, and unpaid completion is rejected. Test lost callbacks and
timeouts as well as successful flows before enabling Production.

If Daraja accepted an STK request but the HTTP response and callback were both
lost, the app cannot discover its checkout ID: the durable Initiated attempt
blocks retry until Safaricom investigates. If a query reports success but
callback metadata never arrives, it likewise remains unresolved rather than
guessing the receipt or amount. Resolve these cases with Safaricom; do not
manually set Paid, delete payment records, or repeat the charge.

## Administration, analytics, and reporting

The Administration dashboard is available at `/#admin-dashboard`. The methods
are exposed through
`/api/method/intelligent_ordering.api.administration.`:

| Method | Purpose | Access |
| --- | --- | --- |
| `dashboard` | Business, inventory, and delivery counts | Store, finance, inventory, or delivery staff |
| `sales_analytics` | Daily/weekly/monthly/yearly verified sales and product/category/area breakdowns | Store or finance staff |
| `filter_options` | Product and category selectors | Store or finance staff |
| `list_customers` / `customer_activity` | Customer profiles, aggregate activity, order history | Store staff |
| `product_performance` | Product units and item sales from paid orders | Store staff |
| `admin_order_detail` | Order snapshots plus payment and delivery history | Store staff |
| `audit_events` | Search administrative audit history | System Manager, Business Admin, Store Manager |
| `export_report` | CSV or XLSX sales, order, customer, payment, stock, or delivery report | Role-scoped by report |

Sales are defined as the sum of verified successful Payment Transaction
amounts, grouped by the transaction date (not order or completion date).
Filtering an analytics chart to a non-successful payment status therefore
returns no sales. Product and category breakdowns report the item-line value
of orders with a verified successful payment and exclude delivery fees;
delivery-area totals use the verified payment amount. Category attribution
uses the immutable category snapshot captured on newly placed orders.
Existing records that predate this field remain uncategorized.

The dashboard reads actual Frappe records: order and payment counts, verified
sales, active-warehouse on-hand/available/reserved units, low/out-of-stock
product counts, and delivery-status counts. A low-stock threshold of five
units is used for the dashboard metric. There are no seeded or synthetic analytics.
Date, product, category, order-status, and payment-status filters are
validated server-side. Inventory exports are current balance snapshots and
reject date/order/payment filters. Exports are permission checked, protect
spreadsheet cells from formula injection, and fail explicitly above 50,000
rows so data is not silently truncated. XLSX uses Frappe's bundled
`frappe.utils.xlsxutils` helper.

Order management reuses the Sales Order workflow and displays immutable
customer/product/order snapshots together with payment and delivery history.
Catalog and category editing links to the existing Frappe Desk DocTypes.
Products referenced by order items or stock-ledger history cannot be deleted;
disable them instead. Inventory adjustments continue through the existing
ledger-backed `inventory.adjust_stock` API. Delivery assignment and tracking
reuse the Delivery workflow. Payment history remains read-only except for
provider-backed reconciliation; no administration endpoint can fabricate a
payment confirmation or replace provider references.

The app roles include `Customer`, `Store Manager`, `Finance Manager`,
`Inventory Manager`, `Delivery Manager`, and the existing `Business Admin`,
`Order Manager`, and `Delivery Staff` roles. System Manager retains Frappe's
full administration privileges. Store managers manage products, customers,
orders, and business reports; finance managers view payment/sales reporting
and perform provider-backed reconciliation; inventory managers use the
existing stock APIs and inventory reports; delivery managers assign and track
deliveries. Endpoints enforce role checks server-side, independently of
dashboard visibility.

`Admin Audit Log` is append-only. It records actor and timestamp for product
and category creation/changes, order status changes, payment status changes
and reconciliation requests, stock receipts/issues/adjustments/returns,
delivery creation/status/assignment/scheduling, and user creation/profile/
role changes. Detailed stock movement and delivery activity remain in their
existing append-only ledger/activity records as well.

The standalone validation suite includes date/filter/period/report filename
and spreadsheet formula-injection tests. Database-backed dashboard, chart,
CSV/XLSX, and permission tests are in
`intelligent_ordering/intelligent_ordering/tests/test_administration.py`;
run them on an installed test site using the Bench command above. Role
permission updates and the new DocTypes require `bench --site <site> migrate`.

## Foundation boundaries

- The initial data model is for one business. Marketplace tenancy and vendor
  isolation are deferred.
- Customers have read access to their own profile, addresses, and orders;
  app staff have role-scoped operational access.
- Customer write workflows are not exposed yet. Add them through validated
  server-side methods that verify ownership rather than enabling unrestricted
  generic document writes.
- The project is a research/demo prototype. Use synthetic data and payment/SMS
  sandbox environments until live-operation requirements are approved.
