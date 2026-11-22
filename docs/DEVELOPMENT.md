# Development setup

This repository contains a custom Frappe app. The Frappe framework and MariaDB
are managed by a Frappe Bench installation; this repository is installed as an
app inside that bench. The root `README.md` contains the product overview,
feature status, quick start and commercial launch checklist.
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

Open the site URL printed by `bench start`. The SmartO homepage and dedicated
catalog are available at `/` and `/products`; the existing database-backed
ordering and staff operations remain at `/store`. Frappe's login and session
handling provide the authentication foundation. Administrator/System Manager
can create named customer/staff accounts at `/dashboard/accounts`; use Desk
for advanced permissions.

## ERPNext accounting compatibility

Do not install ERPNext on an existing SmartO site. Both apps define `Sales
Order`, `Sales Order Item` and `Stock Ledger Entry` with incompatible schemas
and controllers. Installing or migrating both apps without first resolving
those collisions risks existing order and stock data.

Same-site ERPNext accounting is not implemented. It requires a tested,
data-preserving migration of SmartO's conflicting DocTypes and references
before ERPNext is installed, followed by a separately validated accounting
integration. Rehearsal must cover backup and restore, existing order and
stock history, permissions, payment reconciliation and duplicate-posting
prevention on a representative isolated site. Do not post pending payments
as received or assume that existing SmartO records have been booked in ERPNext.

## Multiple businesses: one site per business

Each business must use its own Frappe site and database. Install the same app
on each site; do not share or point multiple sites at one database:

```bash
bench new-site business-a.example.com
bench --site business-a.example.com install-app intelligent_ordering
bench new-site business-b.example.com
bench --site business-b.example.com install-app intelligent_ordering
```

Configure DNS and HTTPS for each hostname, route requests to the matching
Frappe site, and verify that each site's `site_config.json` has a distinct
database and database credentials. Configure users, roles, products, inventory,
policies, delivery areas, scheduler, and payment/SMS/Gemini credentials
separately for each business. Use business-specific payment callback URLs and
provider accounts; do not put site-specific credentials in
`common_site_config.json`. Restrict cross-site administrators, backups, logs,
and file storage, and test that a user and order created on one site cannot be
read on the other. Back up and restore each site independently.

This deployment model provides separate stores, not a shared marketplace or
cross-business checkout. Isolation depends on correct Frappe site, database,
host, cookie, storage and administrator configuration; it is not guaranteed by
application-level tenant filters. Validate isolation on the actual deployment
before onboarding businesses.

For example, `shop-a.example.com` and `shop-b.example.com` can run the same
SmartO app version while maintaining separate users, products, stock ledgers,
orders, delivery staff and payment credentials. Each business's managers use
their own site's dashboards, and payments use that site's configured Daraja
account and callback. Customer accounts and carts are not shared across stores.
Business staff must not receive infrastructure-level access to other sites.
The platform operator provisions and maintains each site; vendor self-signup,
cross-vendor search/cart, commission calculation and split settlements are not
implemented. A shared marketplace would require a separately designed
ownership, permission and settlement model rather than simply adding a vendor
field to products.

## Business onboarding and launch checks

After updating the app, run `bench --site <site-name> migrate` and build assets.
Migration adds SmartO public business identity fields to the existing
**Website Settings** singleton, without a second business/settings DocType.
Open `/dashboard/setup` from the Administrator dashboard.

System Managers can save a business name, public support email/phone and public
address. At least one contact is required. Names appear beside the SmartO
storefront branding and in the footer; the contact page uses the saved contact
details. Only these public fields are added to website context; provider
credentials and other private settings are never returned by the setup API.
Changes, including Desk edits, record field names in the existing Admin Audit
Log without copying contact values into the audit details.

System Manager and Business Admin can read
`intelligent_ordering.api.onboarding.readiness`; saving through
`intelligent_ordering.api.onboarding.save_business` is POST-only and requires
System Manager. This narrowly scoped API saves only the four validated public
fields with elevated document permissions; it does not grant general Website
Settings access. Normal Frappe permissions still apply to Desk.
Business Admin does not gain access to System Settings or user management.

The read-only report checks schema, identity, published policies, enabled
catalog/category records, positive saleable stock, delivery areas matching
catalog currencies, named staff accounts, configured HTTPS origin, disabled
developer mode, scheduler flags and production M-Pesa configuration with a
same-origin callback. An installed product without stock does not imply it is
saleable. The stock check requires at least one saleable product, not stock for
every catalog item. Optional SMS/Gemini integrations show their enabled state
only, not validated credentials.

These are configuration/database checks, not external probes: an HTTPS string
does not prove a valid certificate; enabled scheduler flags do not prove a
running worker; a production credential configuration does not prove provider
approval or successful payments. The workspace always lists separate unverified
manual tasks for workflows, providers, backup/restore, infrastructure, site
isolation and policy review. It does not persist success checkboxes or certify
readiness. Keep actual verification evidence in restricted deployment records.

Create initial records through the existing Desk/workspace tools. Standard
Frappe Data Import can be used for supported master data after testing a small
import. Do not import balances, successful payments or status transitions to
bypass inventory, payment or order APIs. Publish approved policies rather than
the seeded review drafts.

## SmartO website routes

The public website uses native Frappe `www` routes and a shared Jinja layout;
it does not add a JavaScript framework. The shared layout provides the SmartO
header, responsive navigation, breadcrumbs, account links, footer, and
route-aware page labels.
The shared SmartO layout uses Frappe's full-width mode without its standard
website sidebar. Header, content and footer use the available width with
one-rem side gutters instead of stacking centered desktop width limits;
individual forms and readable text retain their own width constraints.

| Route | Current page |
| --- | --- |
| `/` | SmartO homepage |
| `/about` | About SmartO |
| `/products` | Searchable, filterable, sortable product catalogue |
| `/assistant` | Opt-in Gemini shopping assistance and customer-scoped recommendations |
| `/products/<product_id>` | Database-backed product details |
| `/product-details?product=<product_id>` | Product details for identifiers that cannot be used as a path segment |
| `/categories` | Enabled product categories |
| `/cart` | Database-backed customer or browser-saved guest cart |
| `/checkout` | Authenticated checkout with server-calculated delivery quote |
| `/payment` | Payment page shell |
| `/order-confirmation/<order_id>` | Owner-scoped order confirmation |
| `/order-confirmation?order=<order_id>` | Confirmation for identifiers that cannot be used as a path segment |
| `/track-order` | Tracking page shell |
| `/contact` | Configured public business contact details, with an explicit unconfigured state |
| `/login` | SmartO login using Frappe authentication, sessions, and verification challenges |
| `/register` | Customer-only registration with published Terms and Privacy acceptance |
| `/forgot-password` | Generic-response password recovery through Frappe |
| `/reset-password`, `/update-password` | SmartO password reset using Frappe reset keys |
| `/terms`, `/privacy`, `/refund-policy`, `/delivery-policy` | Current published policy versions |
| `/account` | Owner-scoped order history and payment controls |
| `/dashboard/owner` | Role-protected business workspace |
| `/dashboard/admin` | Role-protected administration workspace |
| `/dashboard/setup` | Administrator onboarding and configuration/manual launch checks |
| `/dashboard/sales` | Role-protected sales workspace |
| `/dashboard/orders` | Role-protected order search, details and status updates |
| `/dashboard/inventory` | Role-protected inventory workspace |
| `/dashboard/products` | Authorized product creation/editing and category creation |
| `/dashboard/delivery` | Role-protected delivery workspace |
| `/dashboard/rider` | Delivery Staff workspace for offers and assigned deliveries |
| `/dashboard/support` | Read-only customer search, profiles, order history and enquiries |
| `/store` | Existing database-backed storefront and staff workflows |

Adding a product keeps the customer on the catalogue so they can continue
shopping. A successful addition displays **View cart and continue to checkout**
beside its confirmation; catalogue and detail pages also have a prominent cart
link. The cart reviews quantities before `/checkout`, where guests must sign in.
Checkout, confirmation, and payment pages provide **Order history** (`/account`)
and **Checkout** (`/checkout`) buttons. Customer order-history navigation does
not send users to the combined `/store#order-history` operations page.
The existing `/store#admin-dashboard` and `/store#payment-dashboard` links show
only the selected dashboard, without unrelated store sections. Hash navigation
and browser back/forward update the view and refresh its data. This presentation
filter does not change backend role checks or grant access to either dashboard.

Staff dashboards and the two `/store` management views use a shared vertical
sidebar. Navigation includes role-filtered quick access matching the administrator
dashboard: setup, reports, payments, orders, stock, deliveries, delivery areas,
products, customers and audit logs. Account, role, permission and system-setting
shortcuts remain Administrator/System Manager-only. Website pages open their
dedicated workspaces; advanced configuration links open native Desk tools.
On guarded dashboard routes, authorized sidebar entries and the desktop layout
are rendered by the server, not left hidden pending the current-user JavaScript
request. After deployment, clear the site/website cache and reload the page to
pick up template changes. Shopping
and customer-account pages keep their normal header navigation and a staff
workspace link when authorized. The sidebar collapses to labeled-by-tooltip
icons on desktop and opens as a focus-contained drawer on screens up to 850px.
Escape, the close button, the backdrop, and navigation links close the drawer.
Active highlighting follows both dashboard paths and management-view hashes.
Lucide SVG icons are bundled locally with their license in
`public/images/lucide-LICENSE.txt`; no external icon service is required.

### Checkout address and delivery-area choices

The saved-address selector is populated only from the signed-in customer's
addresses at `/account/addresses`. If there are none, the customer can still
type the address directly into the required fields below the selector, or save
an address in My account first.

The delivery-area selector is populated from enabled **Delivery Area** records
whose currency exactly matches the cart's currency. If it is empty, sign in
with System Manager, Business Admin, Store Manager, or Order Manager, open
**Delivery areas and fees** from the admin dashboard (or `/dashboard/delivery-areas`),
and create or enable an area with the correct
currency (for example, KES when the cart subtotal is in KES) and a delivery fee.
An area with another currency, or a disabled area, will not appear. After saving
it, reload checkout. The backend verifies the selected enabled area and its
server-side fee before accepting an order.

Use **Edit area** to change its fee, currency or enabled status, and **Add new
area** to start a separate record. Names are immutable; disable an old area
and create a new one instead of renaming it. Saves reject stale versions.
Administrator/System Manager and Business Admin can delete unused areas after
confirmation. Orders, deliveries and native link checks prevent deletion of
referenced areas; disable those areas instead. Website changes are recorded
in Admin Audit Log. Fees already saved on orders and deliveries do not change.
Run site migrations when deploying the updated delete permissions.

Customer and staff pages reuse the existing database-backed catalog, cart,
checkout, order, inventory, delivery, payment, and reporting APIs. The account,
orders, inventory, and delivery workspaces use the current user's records and
server-enforced permissions; pages do not grant API or DocType access.
Frappe remains the authentication authority; `/login` and password recovery
are rendered by SmartO without displaying the default Frappe login interface.

### Authentication and policy setup

Run `bench --site <site-name> migrate` and rebuild assets after deploying these
changes. Authentication adapters use the Frappe v15 login, two-factor challenge,
password-strength, and password-reset contracts. Verify compatibility with the
installed Frappe release before deploying to production.

In Desk, System Manager or Business Admin can open **SmartO Policy Version**.
Migration adds four **unpublished** drafts with version `smarto-operations-2`,
even when a site already has older policy versions. Existing records are not
changed. Review each draft against your business's legal identity and contacts,
applicable law, provider and data-retention practices, and actual delivery and
refund commitments. After approval, edit the plain text, remove the review
notice and instructions, and set Status to Published. Keep the seeded version
identifier on these records so future migrations do not recreate them.
Registration remains blocked until both Terms and Conditions and Privacy Policy
are published. Drafts are never displayed publicly. Publication time is assigned
by the server, and public pages show the latest published version.

Published versions cannot be edited or deleted. To update a policy, create a
new draft with a different version and publish it after review. **SmartO Policy
Acceptance** records retain the user, customer, exact Terms/Privacy references,
server-assigned acceptance time, and separate optional marketing consent.
These records are read-only, including for administrators. Existing customer
accounts are not retrospectively assigned consent; this change records acceptance
for new registrations and does not authorize marketing to existing customers.

Registration uses Frappe User password handling and creates a Customer Profile
in the same request transaction. Public signup cannot assign staff roles or
bypass the policy gate. Passwords require at least 12 characters, a strength
score of 3, and any additional configured Frappe password policy. Staff accounts
can be created at `/dashboard/accounts` by Administrator/System Manager,
using native Frappe password-setup email. Advanced permissions remain in Desk.

Configure outgoing email for password recovery, enable the site's login
attempt limits/password policy/reset-link expiry, and serve production traffic
over HTTPS for secure session cookies. Session duration remains governed by
Frappe System Settings; SmartO does not add a persistent "remember me" token.
After reset, other sessions are revoked and the reset session is signed out.
Login destinations are selected server-side from existing workspace permissions.
Native Desk access remains subject to Frappe authorization.

Offline regression suites do not establish actual session/email behavior.
Login, customer-account and staff dashboard errors include a safe operation
name and, when available, HTTP status. Server traceback details are not shown
for server errors. When reporting an issue, share the page, action, displayed
error and time; do not share passwords, session cookies, reset links, customer
details or transaction data. If a page reports that its interactive script did
not start, check browser developer tools and deployed assets, and redact any
sensitive data before sharing diagnostics.
On a dedicated development site, run the Frappe integration tests:

```bash
bench --site <test-site> run-tests --app intelligent_ordering --module intelligent_ordering.intelligent_ordering.tests.test_authentication
```

Also verify `/login`, `/register`, guest/unauthorized dashboard redirects,
logout, a real reset email link, token expiry/reuse, and enabled two-factor
authentication using that site's accounts before production deployment.

After changing website templates, route rules, or public assets, rebuild app
assets and restart the Bench site:

```bash
bench build --app intelligent_ordering
bench restart
```

If a page still shows an old catalogue placeholder, check that the running
Bench uses the intended app checkout and site. From that Bench directory:

```bash
git -C apps/intelligent_ordering log -1 --oneline
bench --site <site-name> clear-cache
bench build --app intelligent_ordering
bench restart
```

Replace `<site-name>` with the confirmed existing site name, then reload `/`,
`/products`, `/categories`, and `/cart` in a browser. If the old page persists,
check for a site-specific Website Page or route configuration using the same
route before making changes; do not delete site records without reviewing them.
Check the browser console and server logs for asset or API errors. An empty
catalogue can also mean there are no enabled products in enabled categories;
products need available stock before they can be added to the cart.

## Customer portal

The existing Customer role is a website-only role. `/register` creates real
Frappe Website Users with only Customer assigned; native `/login` signup uses the
same restricted path, ignoring configurable Portal Settings signup roles.
Registration respects Frappe's disabled-signup setting and is rate-limited.
Frappe sends the password setup email when email delivery is configured.
Without an outgoing email account, registration explicitly asks the customer to
contact the store; it does not pretend that an email was sent. Native `/login`,
password recovery, and session logout remain the authentication authority.
Customers land on the storefront homepage (`/`) after login by default.
My account remains available at `/account`; explicit authorized return links
to checkout, payments or account pages are preserved. The Customer
default role-homepage hook points to `/`, without replacing
any explicitly configured Frappe role/portal homepage.

Customer pages are `/account` (orders, payments for an order, and tracking),
`/account/profile`, `/account/addresses`, `/account/payments`, and
`/account/notifications`. Signed-in non-customers are denied these pages.
The `www/account/` directory must retain its `__init__.py`: it makes the
account controller importable as a package for nested routes. The sibling
`www/account.py` is retained for Frappe's `/account` controller discovery.
After deploying a package-layout change, restart web processes and clear the
site cache so a previously imported controller module is not reused.
Guest pages show a sign-in action; backend customer methods require a Customer
session. Customer IDs, roles, payment statuses, and order totals are not accepted
by the portal's profile/address/cancellation forms.

The customer API is `intelligent_ordering.api.customers`. It derives profiles
from the authenticated user, validates address and order ownership before
mutation, and exposes only selected public payment/delivery fields.
At `/account/payments`, signed-in customers can search only their own orders'
payments using a full M-Pesa payment phone number or a full recorded M-Pesa
receipt reference. Phone input accepts local or international Kenyan formats;
receipt matching is case-normalized. Search filters persist through pagination
and refresh; Clear search returns to the first unfiltered page.
`payment_history` accepts optional `search` and `search_by` (`phone` or
`receipt`) parameters. Matching is exact and always constrained by order
ownership, even if customers use the same payment phone number. This reads
existing records, does not query Daraja, and cannot discover a missing callback
or verify a pending payment merely from a customer-entered receipt.
Customers retain read-only DocType permissions; scoped workflow methods perform
validated profile/address changes. Order totals and historical contact/address
snapshots remain unchanged. Addresses referenced by orders cannot be deleted.
The checkout picker copies a saved address into the existing checkout fields;
the server still creates or reuses an address under the authenticated profile.

Order details poll persisted order/payment/delivery state every 15 seconds while
the page is visible, with an explicit refresh button. No GPS position is
invented. New orders and subsequent order, delivery, payment, or cancellation
updates create native Frappe Notification Log records for the owning customer.
Order-list **View details** expands within the selected order card, including
on staff/support pages and the combined store view, rather than below the full
list. Selecting another order moves the detail view to that card.
The notification list and mark-read operation are recipient-scoped. SMS is an
independent, optional delivery channel described below; historical notification
events are not backfilled.

### Africa's Talking SMS

The existing Fulfillment Notification outbox records customer SMS events for
confirmed orders, persisted payment status transitions, delivery assignment,
dispatch, completion and failure. Messages go to the phone saved on the order,
not the rider's phone. A payment is described as successful only after the
existing verified payment workflow records it as Successful.

Create an Africa's Talking account and obtain the username and API key from its
dashboard. For testing, use the sandbox username `sandbox` and sandbox API key;
for production use your live username and key, sufficient SMS balance, and an
approved sender ID if required by the destination. Configure the following
nested object in the site's private `sites/<site-name>/site_config.json` or
deployment secret configuration. Never commit credentials:

```json
{
  "fulfillment_notifications": {
    "provider": "africas_talking",
    "enabled": true,
    "environment": "sandbox",
    "username": "sandbox",
    "api_key": "YOUR_SANDBOX_API_KEY"
  }
}
```

For live sending change `environment` to `production` and use the live
credentials. Optionally add `"sender_id": "YOUR_APPROVED_SENDER_ID"`; omit it
when not needed. Local Kenyan mobile numbers and international numbers in E.164
format are accepted. Invalid or missing order phone snapshots produce a Failed
event; retrying alone cannot correct an immutable order snapshot.
`.env.example` is reference only and is not loaded by Frappe.

After updating the app and configuration, run `bench --site <site-name> migrate`,
enable the scheduler with `bench --site <site-name> enable-scheduler`, and ensure
the Bench scheduler and workers are running. The scheduler processes up to 20
prepared events per run. Test with a sandbox test number and inspect Fulfillment
Notification records in Frappe Desk; verify production routing, sender approval,
provider balance and charges with Africa's Talking before going live.

Events capture their configured provider and environment at creation. Events
created before Africa's Talking is configured are not sent later. Disabling the
integration pauses already-prepared Africa's Talking events, which resume when
it is re-enabled in the same environment. Switching environments does not send
the other environment's queue. Invalid configuration is logged without exposing
secrets. Provider authentication errors are recorded as uncertain outcomes;
neither condition prevents orders or payments from being saved.

`Submitted` means the provider accepted the request, **not** that the handset
received the SMS; delivery receipts are not integrated. `Failed` means local
validation failed or the provider explicitly rejected the recipient.
`Unknown` or a stuck `Sending` may already have reached the provider: investigate
the provider records and do not blindly resend. Timeouts and ambiguous responses
are never automatically retried. After correcting a definite rejection, a
System Manager or Business Admin can request an audited retry with a POST to
`/api/method/intelligent_ordering.utils.fulfillment_notifications.retry_failed_sms`
and `name` set to the Fulfillment Notification name. Only Failed events can be
retried; the scheduler sends them when enabled. Keep access to these records and
provider logs restricted because they contain customer phone numbers.

Customers may submit a cancellation request with a reason for an open order.
Only one pending request is allowed at a time; rejected requests may be
resubmitted with a new reason, preserving the earlier requests and decisions in
the immutable audit log.
It does not immediately cancel or refund anything. Order managers review it in
`/dashboard/orders`, supplying a response when approving or rejecting.
Approval uses the existing cancellation transition, stock-return/reservation,
and delivery safeguards. A blocked approval leaves the request pending.
Closed orders cannot receive new requests. Six read-only
cancellation fields are added to **Sales Order**; no new app DocTypes are added.
Requests and resolutions are recorded in the existing immutable audit log.

### Local test customer

From your private developer-mode Bench site, with `bench start` running:

```bash
bench --site smart.localhost migrate
bench build --app intelligent_ordering
bench --site smart.localhost clear-cache
bench --site smart.localhost execute intelligent_ordering.utils.development_accounts.provision_customer
```

Confirm `LOCAL-ONLY smart.localhost`. At the hidden password prompt, enter the
temporary customer password supplied for this task. It is deliberately not
stored in source code, command-line arguments, or the command result.
The command creates **SmartO Test Customer**, `customer.test@smarto.local`, as a
Website User with only Customer. It never changes Administrator or existing
matching account passwords and aborts on conflicting roles/settings. If the
account already exists, use its existing password or the native password reset
flow; provisioning does not overwrite it.

Hard-refresh the browser, sign out of staff sessions, and open `/login` using
that email and the password you entered. Open `/account/profile` and save a phone
number, add an address, then browse `/products` → `/cart` → `/checkout`.
Keep the same site hostname throughout so cookies and guest-cart storage stay
on the same origin. Private-IP HTTP supports checkout retry tokens, but **use
HTTPS for production and anywhere credentials travel over untrusted networks**.

Verify actual HTTP login and read-access boundaries:

```bash
bench --site smart.localhost execute intelligent_ordering.utils.development_accounts.verify_customer
```

Enter the private site base URL and password at the prompts. It checks identity,
Customer-only roles, permitted portal APIs, denied staff APIs/dashboard URLs,
and read denial for another customer's order/payments when a fixture exists.
Missing fixtures are reported as NOT TESTED, never PASS. It makes no business
writes or provider calls. Browser CRUD, registration email delivery, cancellation
approval, and payment-provider tests must also be performed on a test site.

The standalone tests exercise validation, scoped API queries, registration roles,
forms, and retry safety. Database integration tests in `test_checkout.py` also
cover native password checking, real address CRUD, immutable snapshots,
cancellation, notifications, and cross-customer denial:

```bash
bench --site <private-test-site> run-tests --app intelligent_ordering \
  --module intelligent_ordering.intelligent_ordering.tests.test_checkout
```

Only use development accounts/passwords on a private development site. Do not
provision them on a publicly reachable or production site.

## Configuration and secrets

Copy `.env.example` only as a reference for the external credentials that
future integrations may require. Frappe does not load it automatically.
Configure database/site settings using Bench and store provider secrets in
the site's `site_config.json` or the deployment secret manager. Do not commit
credentials or production site configuration.

Payment, SMS and the optional Gemini assistant call external providers when
configured. Mapping and road-routing services are not integrated.

### Gemini shopping assistant

The home page and `/assistant` provide the shopping assistant to signed-in
Customer accounts. Obtain a
Gemini API key from Google AI Studio and configure each site's private
`site_config.json` (merge this object into the existing file):

```json
{
  "gemini": {
    "enabled": true,
    "model": "gemini-2.5-flash",
    "api_key": "YOUR_GEMINI_API_KEY"
  }
}
```

Use a model available to the account and verify Google's current pricing,
terms and data handling before enabling it. This is disabled unless explicitly
configured. `.env.example` is reference only and is not loaded by Frappe.
Requests are rate-limited and require an explicit checkbox acknowledging that
the current message, recent conversation and matching public product data go
to Gemini. Do not enter personal, financial or authentication information. The
server rejects common phone/email patterns, but this is not comprehensive
redaction. Conversation history remains in the browser page and is not stored
as a SmartO record; Google may retain data according to its terms.

The assistant has no access to private order history, payment transactions or
customer profiles and cannot place orders or modify payments. Suggested product
IDs and quantities are checked against the live public catalog and stock; the
customer must explicitly add each suggestion through the existing cart API and
complete checkout normally. Product availability and totals are revalidated by
the existing workflows. AI replies can be inaccurate and must not be treated as
authoritative payment, delivery or policy information.

The separate **Load my suggestions** action uses only the signed-in customer's
completed orders and historical product categories, ranking currently enabled,
in-stock products. It sends no purchase history to Gemini. Customers without
completed purchase history receive an empty result.

Voice input is optional and requires a supported browser in a secure context
(HTTPS or localhost). The customer must opt in to the browser's speech
recognition service, which may send audio to its provider. Recognized text is
editable and is never submitted automatically; Gemini consent remains
separate. Optional spoken replies use browser speech synthesis. Do not speak
personal, financial or authentication information. Unsupported browsers retain
the typed assistant.

### Forecasts

Owner and finance workspaces show seven-day sales and demand estimates;
inventory staff can view demand estimates. A local weekday-seasonal linear
trend fits at most 56 complete days and requires at least 28 days of history
and five days with activity; otherwise it reports insufficient data. Sales
use only successful payment transactions, grouped by transaction date,
currency and sandbox/production environment. Demand uses completed order-item
quantities by order date for up to 20 recently popular enabled products.
Today is excluded from training because it is incomplete. These are statistical
baselines, not guarantees: stockouts, promotions, holidays, returns, changing
business hours and short history can make the estimates inaccurate. They do
not modify orders, payments or inventory.

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
customer cart. Cart review and checkout are available on their dedicated pages.
Product images intended for guests must be accessible to website visitors.

### Website product management

At `/dashboard/products`, System Manager, Business Admin, Store Manager,
Order Manager and Inventory Manager can list enabled/disabled products, search
by SKU/name, create products and edit existing records. The APIs in
`intelligent_ordering.api.products` enforce this role boundary and normal
Frappe document create/write permissions, including custom permission
restrictions. Edits require the loaded modification timestamp; stale writes
must be reopened. SKUs are immutable in this workspace. The price must be
finite and non-negative, and category/currency validation retains the existing
Product controller. Category creation uses normal Product Category create
permissions, so Order/Inventory Managers cannot create categories by calling
the API directly.

Images use Frappe's native authenticated file upload endpoint, attached to
the saved Product as public files. Only public PNG/JPEG/WebP/GIF file references
attached to that product are accepted by the product-save API. Upload and
linking are separate operations; failures explicitly distinguish a confirmed
upload from an unconfirmed product update. Old attachments are not deleted
automatically. Do not upload sensitive images. Product changes and category
creation use the existing Admin Audit Log hooks.

Creating a product does not create stock. Only System Manager, Business Admin
and Inventory Manager receive goods through `/dashboard/inventory` and the
existing `inventory.adjust_stock` API; Store/Order Managers retain product-only
authority unless separately assigned an inventory role. Select the product,
active warehouse and Receipt (or Opening only for initial balances), then enter
a whole quantity and remarks. No direct balance writes or duplicate stock
modules are introduced. Warehouse setup remains in Desk.

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

The storefront and dedicated cart include quantity controls, removal and clear
actions, subtotals, and totals. Guest carts are merged after sign-in; checkout
requires an authenticated Customer role.

## Checkout and order management

Checkout and order methods are available through Frappe's standard method API:

- `GET /api/method/intelligent_ordering.api.checkout.get_checkout`
- `POST /api/method/intelligent_ordering.api.checkout.get_checkout_attempt`
- `POST /api/method/intelligent_ordering.api.checkout.create_order`
- `GET /api/method/intelligent_ordering.api.orders.get_my_orders`
- `GET /api/method/intelligent_ordering.api.orders.get_my_order`
- `GET /api/method/intelligent_ordering.api.orders.get_order`
- `GET /api/method/intelligent_ordering.api.orders.list_orders`
- `POST /api/method/intelligent_ordering.api.orders.update_order_status`

Checkout returns the current server cart and a revision for the customer to
review. Order creation requires the revision, a unique request token, customer
contact information, and a delivery address. Product prices and totals are
re-read and calculated from Product records; browser-submitted prices and
totals are not accepted. The cart is cleared only after the Sales Order has
been inserted successfully. Repeating a request token for the same customer
returns the existing order. Checkout rechecks stock under inventory locks, but
does not reserve it: reservation happens when staff confirm the pending order.
Consequently, multiple pending orders can compete for the same stock.

The dedicated checkout stores its request token and a SHA-256 submission
fingerprint in session storage before submission, and the order reference when
known. HTTPS uses a hashed fingerprint; private HTTP fallback stores the exact
submission (including contact/address fields) in tab-scoped session storage for
retry comparison. Recovery state is cleared after the owned order is loaded.
After an interrupted
response or reload, it checks the token against the signed-in customer before
recovering an existing order. An uncertain attempt can only be retried with the
same reviewed cart, quote and customer details; contact the store if these cannot
be restored. A definitive validation rejection allows a corrected new request.
Session storage recovery is limited to the same browser tab.
Private HTTP uses cryptographically random UUID tokens and exact retry
comparison when HTTPS-only digest APIs are unavailable. Use HTTPS in production.
The confirmation and account pages use owner-scoped endpoints even for customer
accounts that also have staff roles. Successful checkout opens
`/track-order?order=<order-name>`, automatically selects that order, and displays
its payment and delivery progress. Customers can see the assigned rider's
display name once one accepts; rider account identifiers and contact details are
not exposed. The existing payment controls are available on the tracking page.

Customers can list and view only their own orders. Business Admin and Order
Manager roles can search and inspect orders. After verified M-Pesa payment, the
scheduler confirms Pending orders through the normal stock reservation workflow,
including previously paid Pending orders. Cash on Delivery confirms at checkout.
The scheduler then advances orders to **Processing**, then to **Ready for
Delivery** after the preparation interval. The default interval is 20 minutes,
configurable per site with `"order_fulfillment": {"preparation_minutes": 20}`.
The interval is captured on confirmation. M-Pesa orders do not become Ready for
Delivery until payment is verified; Cash on Delivery orders can advance with
their pending COD transaction. Ready for Delivery dispatches reserved stock and
starts the existing rider broadcast. Delivery completion and COD finance
reconciliation retain their existing safeguards. Submitted order details and
line prices are immutable; Completed and Cancelled are terminal. Legacy
confirmed/processing orders without preparation timestamps are given a fresh
interval by the scheduler rather than being dispatched immediately. The
scheduler logs blocked validation failures, including insufficient stock, and
continues with other orders; staff must resolve the underlying issue.

The storefront continues to provide checkout review, customer order tracking,
order history, and staff order controls. The dedicated `/account` and
`/dashboard/orders` pages use the same APIs. Completion is performed through
the delivery workflow, not through the staff order status form. Customers can
choose M-Pesa or Cash on Delivery (KES only); M-Pesa must be configured
server-side for payment to work.
New orders include the configured delivery-area
fee in their immutable server-calculated total. Product/category-at-order
snapshots support historical reporting; old orders without a snapshot report
as uncategorized rather than being silently reclassified.

## Personnel accounts and workspaces

Administrator/System Manager can register customers and staff from
`/dashboard/accounts`, linked from the admin dashboard and setup workspace.
Business Admin cannot access this page or its APIs. The page uses existing
Frappe User, Role and Customer Profile records, native create/write permission
checks, password-setup email and existing User audit hooks. It never grants
System Manager or arbitrary roles.

Give each person a named account with one intended role. Customers and the
Store Manager, Order Manager, Inventory Manager, Delivery Manager, Customer
Support and Delivery Staff roles are Website Users with website workspaces,
not Desk access. Finance Manager, Business Admin and System Manager remain
System Users. Available roles are
Customer, Business Admin, Store Manager, Finance Manager, Delivery Manager,
Order Manager, Inventory Manager, Customer Support and Delivery Staff (Rider).
Do not share accounts or grant System Manager merely to open a workspace.

Deploy this change with `bench --site <site-name> migrate`, then clear site and
website caches. The migration updates existing app Role documents through
Frappe's native save lifecycle. Frappe recalculates affected users' types,
preserves their assigned roles and document permissions, and revokes sessions
when the user type changes. Staff must sign in again to their website workspace.
Users with another Desk-enabled role (including custom roles) retain Desk
access; review mixed-role accounts explicitly instead of deleting their other
permissions automatically. Rehearse the migration and role workflows on staging.
Website-only staff can still use their permitted APIs and product/stock/delivery
actions. Native product-image uploads allow PNG, JPEG and GIF for these users;
WebP remains available to Desk-enabled accounts.

Configure outgoing email, email workers and the correct site URL before
inviting anyone. Creation and resending use native Frappe welcome/password-setup
instructions, never administrator-entered passwords or exposed reset links.
Configuration errors fail explicitly; queued email is not confirmed delivery.
Resending can invalidate earlier setup links.

If an invitation reports an outgoing-email error (Frappe may return HTTP 501),
open **Email Account** in Desk and configure the provider's SMTP settings and
credentials. Enable outgoing email, mark the account as the default outgoing
account, and verify the provider's authentication and connection settings.
Save and test the configuration, then retry the invitation. If Frappe reports
that an email was queued but it does not arrive, inspect the Email Queue and
ensure scheduler and workers are running. Never share SMTP passwords or reset
links when requesting support.

Search by name/email, change an operational role, or enable/disable a managed
account. The backend checks the loaded modification timestamp and normal User
write permission, then saves through the native lifecycle and revokes existing
sessions. Resolve/reassign a rider's undelivered assignments before disabling
them or changing their role. Customer/staff conversion is not supported here.
Self-edits, administrator accounts, role profiles and custom/multiple-role
accounts are protected; use Desk for advanced role/permission administration.

Admin-created customers receive an existing Customer Profile but no fabricated
SmartO Policy Acceptance or marketing-consent record. Obtain any required
customer consent through the actual customer process.

| Workspace | Roles permitted to open it |
| --- | --- |
| `/dashboard/accounts` | Administrator/System Manager only |
| `/dashboard/products` | System Manager, Business Admin, Store Manager, Order Manager, Inventory Manager |
| `/dashboard/admin` | System Manager, Business Admin |
| `/dashboard/owner` | System Manager, Business Admin, Store Manager |
| `/dashboard/orders` | System Manager, Business Admin, Store Manager, Order Manager |
| `/dashboard/sales` | System Manager, Business Admin, Store Manager, Finance Manager |
| `/dashboard/inventory` | System Manager, Business Admin, Inventory Manager |
| `/dashboard/delivery` | System Manager, Business Admin, Store Manager, Order Manager, Delivery Manager, Delivery Staff |
| `/dashboard/rider` | Delivery Staff |
| `/dashboard/support` | System Manager, Business Admin, Store Manager, Customer Support |

`Administrator` retains Frappe's administrative access. These page checks do
not grant extra DocType or API permissions; the existing endpoint and document
checks remain authoritative. Delivery Staff access is limited to their
assigned deliveries. Finance reconciliation is restricted to System Manager,
Business Admin, and Finance Manager. Customer order pages use the signed-in
customer's identity, including when that user also has a staff role.
Avoid assigning the Customer role to personnel who update orders: the Sales
Order controller rejects customer modifications. Test access with separate
non-administrator accounts before deployment.

### Local development test accounts

No test accounts are created during installation or migration. The following
Bench-only command creates real Frappe users with role-appropriate Website/System
User types **only on an explicitly
confirmed local/private developer-mode site**. Never run it on production,
an Internet-accessible site, or a local site exposed by a public tunnel.
The built-in `Administrator` user is never changed.

From your existing Bench, using its exact site name:

```bash
bench --site <local-development-site> migrate
bench build --app intelligent_ordering
bench --site <local-development-site> execute intelligent_ordering.utils.development_accounts.provision
```

The site must already have `developer_mode: 1` and a local/private hostname;
the command rejects a configured public `host_name`. Do not enable developer
mode on production to bypass this guard. At the prompt, enter
`LOCAL-ONLY <local-development-site>`, then enter and confirm your chosen
temporary development password. Input is hidden; do not put the password in
command arguments, source files, environment files, or shell history.

| Email | Assigned Frappe roles | Start page |
| --- | --- | --- |
| `admin.test@smarto.local` | System Manager, Business Admin | `/dashboard/admin` |
| `manager.test@smarto.local` | Store Manager | `/dashboard/sales` |
| `orders.test@smarto.local` | Order Manager | `/dashboard/orders` |
| `inventory.test@smarto.local` | Inventory Manager | `/dashboard/inventory` |
| `delivery.test@smarto.local` | Delivery Manager | `/dashboard/delivery` |
| `finance.test@smarto.local` | Finance Manager | `/dashboard/sales` |
| `support.test@smarto.local` | Customer Support | `/dashboard/support` |
| `rider.test@smarto.local` | Delivery Staff | `/dashboard/rider` |

**Password:** for each newly created account, use the temporary password you
entered at the hidden prompt. Keep that value in your local password manager.
Frappe's password policy still applies. The test administrator also needs
Business Admin because several app DocTypes grant administration through that
role rather than System Manager; no other test account receives either role.
Inventory Manager can create/edit products in the product workspace and perform existing
ledger-backed stock operations, but cannot read payment transactions.
Customer Support can read customer profiles and orders, not mutate either or
access payment management. Its page searches the existing Customer Profile
records and opens paginated order history through the role-checked
`administration.list_customers` and `administration.customer_activity` APIs.
Support customer-search responses omit collected-payment aggregates.

Matching existing accounts are reused without changing passwords or roles.
Conflicting roles, role profiles, disabled accounts, or incorrect user types abort
the command before creating users; review those accounts explicitly in Desk.
New-user welcome emails are disabled. Creation errors roll back the batch
rather than leave a partially created set. The command returns account/role
statuses, never passwords.

For independent login and permission checks against these actual accounts:

```bash
bench --site <local-development-site> execute intelligent_ordering.utils.development_accounts.verify
```

Confirm the local-only site again, enter the exact base URL printed by Bench
(including its port), and enter each account's password when prompted. This
checks independent HTTP logins/identity, authorized read APIs, direct dashboard
URLs, prohibited payment-list API requests, DocType permissions, and server-side
order/reconciliation gates under each account. It makes no payment-provider
calls or business-record mutations.
Denied mutation checks are direct server calls, not HTTP/CSRF tests.
The report explicitly marks failed checks and missing delivery fixtures;
`all_passed` is false for either. Assigned/unassigned delivery checks need real
existing delivery fixtures. It does not replace browser/navigation or
end-to-end workflow testing.

For isolated database-backed tests (not your working or production site):

```bash
bench --site <isolated-test-site> run-tests --app intelligent_ordering --module intelligent_ordering.intelligent_ordering.tests.test_role_accounts
```

These tests create transaction-scoped, uniquely named User/Product records;
they do not overwrite the eight development accounts. They check password
authentication and least-privilege permissions, not browser login or CSRF.

For browser testing, log out between accounts or use separate browser profiles,
visit the local site's `/login`, and use the email and password above. Check
that only authorized staff links appear and open a prohibited dashboard URL.
As support, view customer profiles/order details and confirm no payment/status
controls appear. As inventory, edit a product and record stock. As a delivery
manager, assign a real ready delivery to the rider; as the rider, verify that
another person's delivery is inaccessible even using its direct API URL.
As finance, inspect real transaction/report data; do not fabricate successful
payments. Remove or disable these accounts before any public deployment and
do not transfer their passwords into a production database. Existing site
custom permissions, role profiles, MFA, and login policies also need live
verification.

## Inventory management

Inventory methods:

- `GET /api/method/intelligent_ordering.api.inventory.get_dashboard`
- `GET /api/method/intelligent_ordering.api.inventory.list_stock`
- `GET /api/method/intelligent_ordering.api.inventory.list_product_options`
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
Pending without affecting inventory until confirmation. New Cash on Delivery
orders automatically take the normal Pending-to-Confirmed transition during
checkout, reserving available stock atomically with order creation. Insufficient
stock rejects checkout without clearing the cart. M-Pesa checkout remains Pending
until verified payment; the scheduler then confirms it and reserves stock. A paid
order that cannot reserve stock remains Pending and requires staff attention.
Inventory screens
provide dashboard totals, product/warehouse stock search, movements, and
authorized receipt/adjustment controls.

The `/dashboard/inventory` page connects the dashboard, balance search,
movement history, product picker, receipts/adjustments, and dispatched-order
returns to those APIs. The product picker includes disabled products for
authorized inventory staff to manage their existing stock; disabled products
remain unavailable for customer orders. Inventory API permissions remain
authoritative.

For received goods, select the product in **Matching products**, choose an
active warehouse, and use **Receive stock** (the default) with the received
whole-number quantity. **Initial stock** is only for a product/warehouse pair
without prior movements. Submission status and server errors appear beside
the submit button; the product stays selected for subsequent movements.
If saving succeeds but refreshing the display fails, reload and check the
balance/movement history before submitting the same receipt again.

## Delivery management

The rider-specific `/dashboard/rider` page shows delivery offers, the signed-in
rider's assignments and route controls, including for users who also have
manager roles. The `/dashboard/delivery` page uses the existing `deliveries` APIs for
permission-scoped delivery listing/detail, manager assignment and scheduling,
delivery-area management, and assigned-staff status updates. Managers can
create deliveries from ready orders or change assignments. Delivery Managers
can view routing areas; only System Manager, Business Admin, Store Manager and
Order Manager can change area rates.
Delivery staff see their assigned deliveries and minimal details of available
offers. The assigned rider marks delivery after obtaining recipient confirmation
and uploading proof. The customer then confirms receipt from the order tracking
page. A paid order completes after customer confirmation; a COD order completes
only after both customer receipt confirmation and finance verifies the rider's
cash collection. Run `bench --site <site-name> migrate` after installing the
receipt-confirmation fields. Delivery updates do not
deduct inventory a second time. Manager and staff API checks remain
authoritative even when a page is accessible.

On `/track-order` or `/account`, select **View details** for the order. The
receipt button is enabled only after the rider saves the delivery as
**Delivered**; before then it explains why confirmation is unavailable. Order
confirmation and payment pages link to tracking. A direct tracking link loads
the owned order even if it is not on the first order-history page.

The order page's **Assign or monitor delivery** link opens
`/dashboard/delivery?order=<order-name>`, filters the delivery list, and opens the
matching delivery's assignment controls. Automatically broadcast orders already
have a delivery record: use **Assign / monitor delivery** under Deliveries, not
Create delivery. Managers select an enabled Delivery Staff account and scheduled
date; if no rider accounts exist, the form explains that an Administrator/System
Manager must register one at `/dashboard/accounts`. Rider accounts cannot assign
other riders. Manager assignment controls and rider choices load from the
authorized delivery detail, even if the delivery overview fails; overview
errors still require investigation.

Use **Search deliveries** to filter existing delivery records by order or
delivery number. Search updates the list independently of the overview and
shows progress, matching results, or errors beside the filters.

The page separates rider and manager overviews, displays per-rider completion
rates, and filters delayed active deliveries with `list_deliveries(delayed="1")`.
The delayed filter preserves rider ownership. Reassigning before pickup resets
the delivery to Assigned so the replacement rider must accept it; picked-up
deliveries cannot be reassigned. Completion requires the assigned rider's
explicit confirmation, private proof photo, and verified payment, with existing
activity records retaining actors and timestamps.

After a rider accepts, the rider can mark the delivery **Ready for Dispatch**
directly; the older **Preparing** step remains available for existing
workflows. **Save delivery update** shows whether the update was saved in the
delivery details, separately from any overview refresh error. Pickup and
transit still require verified M-Pesa payment or an outstanding COD transaction.
The customer confirms receipt after the rider marks delivery and uploads private
proof. COD also requires the rider to record cash collection before finance
reconciles it; the order completes only after both payment and receipt are
confirmed.

### Automatic delivery offers

When an order changes to **Ready for Delivery**, SmartO creates its existing
Delivery record and starts a broadcast. Riders use their existing Delivery Staff
accounts and choose **Go online** in the delivery workspace. They must keep the
dashboard open; presence expires after 90 seconds without a heartbeat. Riders
with active deliveries do not receive offers. Offers show only the order,
delivery reference and area until accepted; location sharing is not required.

The default is three consecutive five-minute rounds. Rejections apply only to
that rider and persist across rounds. Acceptance locks the rider, order and
delivery, checks eligibility and the current round again, and records the
assignment and acceptance together. A stale offer cannot be accepted after
another rider or manager assigns it. Offers update over Frappe realtime when
available, with dashboard polling as a fallback. Managers can still assign or
reassign deliveries using the existing workflow.

Configure the policy per site in `site_config.json`, for example
`"delivery_broadcast": {"attempts": 3, "round_minutes": 5}`. Attempts must be
an integer from 1 to 20 and round minutes an integer from 1 to 1440. The policy
is captured when each broadcast starts. After the final round, the Frappe
scheduler creates an in-app Notification Log for each enabled Delivery Manager
and lists the delivery in the manager workspace for manual intervention.
Escalation depends on running scheduler workers and may occur after the exact
expiry. If there are no enabled Delivery Managers, the condition is logged and
the delivery still appears in the manager workspace.

Orders already ready before this update are not broadcast retroactively; a
manager can create their delivery to start a broadcast. Legacy orders without
a delivery area retain their original total and may show an unspecified area.
Run `bench --site <site-name> migrate` and rebuild assets after deploying, then
verify competing accepts, notification delivery, and the scheduler on an
isolated Frappe site before production use.

### Delivery planning and rider locations

Run `bench --site <site-name> migrate` after installing the update. A rider can
choose **Share current location** on the delivery dashboard; the browser asks
for location permission and requires a secure browser context: HTTPS, or
localhost on the device running the browser. A private IP over HTTP is not a
secure context. Location and route action results appear beside their buttons.
This captures a single GPS
position, not continuous tracking. Only the rider can share or clear their own
position. The latest position and its reported accuracy are stored in the
Delivery Rider Location DocType, visible only to delivery-management roles.
Clearing it removes the current coordinates; normal database backups may still
contain older data. Locations older than 30 minutes are not used for planning.

A delivery manager opens a delivery and enters verified latitude and longitude
for its delivery-address snapshot. No geocoding service is used. On **Plan a
delivery group**, select that unassigned delivery, a date, a radius and a maximum
number of stops. The planner suggests the nearest enabled, idle rider with a
recent shared location, then groups other unassigned, ready deliveries in the
same area within the chosen radius of the starting delivery. A nearest-neighbor
ordering suggests the stop sequence. The manager reviews the result and
explicitly assigns the group; each delivery uses the existing assignment,
acceptance, history and notification workflows. The server rechecks the rider
and every delivery when assigning, rejecting a plan if its reviewed coordinates
or rider location have changed. Incorrect delivery coordinates can be cleared
from the delivery details. Riders can view a suggested route containing
only their own active, located deliveries; unlocated deliveries are counted
separately.

Distances are approximate straight-line distances, not driving directions or
travel-time estimates. They do not account for pickup location, roads, traffic,
obstacles, GPS uncertainty or rider capacity. Review addresses, rider workload,
vehicle capacity and real road directions before dispatch. Planning does not
change payments, inventory or order totals.

Inventory, delivery-management, order, finance, owner and administrator pages
offer CSV/XLSX exports directly on the page using the existing
`administration.export_report` API. Rider and Support pages do not expose
reports. Report permissions remain authoritative on the server.

### Role-page integration

`/dashboard/sales` embeds the same transaction component used by the legacy
store view. It provides payment-reference/order/receipt search, status filters,
timestamps, associated order status and totals, and authorized reconciliation.
Reconciliation controls follow the backend's `can_reconcile` flag; Store and
Order Managers cannot reconcile payments.

`payments.finance_overview` calculates collected, pending, failed and reversed
amounts, plus daily, ISO-week and monthly verified revenue. Currency balances
are never added together. Outstanding balances exclude cancelled orders and
subtract only Successful transactions, clamped at zero; pending attempts do
not reduce outstanding balances. Reversed payments are not presented as
successful revenue or as a refund-request workflow. Finance also sees
payment-method transaction counts and amounts grouped by method, status and
currency; payment summaries never aggregate different currencies together.

`/dashboard/orders` displays counts for the existing statuses, immutable order
details, cancellation review, order-specific audit history, and linked delivery
assignments. Its delivery link opens the authorized delivery workspace.

Owner and administrator pages display customer search/history and
`administration.management_activity`: low-stock alerts, paid product
performance, rider completion/delays, and append-only staff audit records.
Store Managers can read aggregate inventory health but do not gain inventory
adjustment permissions. Administrator shortcuts reuse native Frappe user,
role, permission, product, customer and system-settings pages.

This integration intentionally preserves the existing lifecycles. It does
not introduce complaints/escalations, refund requests, delivery OTPs, or a
Rejected order status. Those require separately defined business rules and
persisted workflows. Pending orders remain the existing new-order queue.

## M-Pesa configuration and operations

Successful checkout (including a recovered/repeated submission) opens the
owner-only order confirmation, with a link to `/payment?order=<order-name>`.
For M-Pesa orders, the payment page displays the server-calculated order total
and existing payment attempts, and never asks for the customer's PIN. It does
not initiate a charge on page load. The customer explicitly clicks **Pay with M-Pesa**, approves
the prompt on their phone, then uses **Refresh payment status** to view the
verified result. Paid or closed orders cannot initiate another payment.
An unconfigured integration reports an error; it does not offer fake payment
success or switch the order's payment method. Cash on Delivery orders show
collection instructions instead of an M-Pesa prompt.

### Configure this Frappe app

1. In the [Safaricom Daraja portal](https://developer.safaricom.co.ke), create
   an app with M-Pesa Express enabled. Obtain its matching Sandbox consumer key,
   consumer secret, test shortcode, and STK passkey from the portal's test data.
   Do not use unrelated credentials or invent a passkey.
2. On your Bench server, securely edit
   `sites/smart.localhost/site_config.json`. Merge the `mpesa` object shown below
   into the existing JSON; preserve database credentials and other settings.
   This app reads `frappe.conf.mpesa`, not a generic Payment Gateway DocType.
   Never put credentials into browser code, chat, or Git.
3. Configure a publicly reachable HTTPS callback ending in
   `/api/method/intelligent_ordering.api.payments.callback`. A private IP such
   as `172.18.183.58`, localhost, or a LAN-only hostname cannot receive Safaricom
   callbacks. Use a separate controlled sandbox deployment with HTTPS and no
   development passwords; do not expose your existing development/test-account
   site publicly. The proxy must route callbacks to the correct Frappe site.
   Configure the base callback URL without a query string; the app appends its
   per-attempt token automatically.
4. Set the system timezone to `Africa/Nairobi`. Restart the Bench services after
   changing configuration (`bench restart` for managed services; stop and
   restart `bench start` in development). Run `bench --site smart.localhost
   clear-cache`. No secret should appear in command arguments or shell history.
5. Test Sandbox order placement, explicit STK initiation, callback processing,
   failures, and duplicate refreshes. Only after Safaricom approval use matching
   Production credentials and an approved business shortcode on a separate
   production site. Do not mark an order paid manually when a callback is missing.

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
is stored. The callback URL sent to Daraja includes the token. The callback
reads exactly one token from the URL query, including for JSON requests, and
rejects missing or duplicate tokens. Treat callback
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
| POST | `confirm_cod_payment(payment_name)` | Finance reconciliation roles, after rider-recorded cash collection |
| POST | `expire_unpaid_order(order_name)` | Staff-only configured expiry/cancellation |

Payment staff are Business Admin, Store Manager, Order Manager, Finance
Manager, and System Manager. They can
open **View payment** to display details inside the selected transaction card.
Authorized reconciliation uses **Check with Safaricom** at the top of the
expanded details, before the transaction fields and technical diagnostics;
there is no separate detail panel to scroll down to. Loading and detail-request
errors are shown inline, and refreshing the list retains the selected card's
details while that payment remains in the results. They can
inspect raw callback/query records but cannot edit statuses through generic
DocType writes. Receipt and checkout IDs are unique. M-Pesa cannot be manually
marked paid and the app never collects a PIN. Cash on Delivery (KES only) creates
an outstanding transaction and auto-confirms the order using normal stock
reservation at checkout. Payment remains Unpaid. The assigned rider records collection
at handover as delivery evidence but cannot change payment status. Finance
Manager, Business Admin, or System Manager can confirm only a delivered COD
order with matching rider, amount, and collection timestamp; this records the
payment audit event and completes the order. Pending COD amounts are outstanding,
not revenue. Reversed is reserved in the schema; this module does not initiate
reversals or manufacture reversal confirmations.

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

Successful payment marks `payment_status = Paid`. The scheduler confirms paid
Pending M-Pesa orders, reserving stock on confirmation and dispatching at Ready
for Delivery. For COD, the rider can dispatch and deliver while the order remains
unpaid only after recording cash collection and private proof of delivery.
Finance confirmation then marks it paid and completes the order. Other unpaid
orders cannot be dispatched or completed. Failed attempts do not change the
order or automatically release reservations. Cancellation remains a staff
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

The Administration dashboard is available at `/store#admin-dashboard`. The methods
are exposed through
`/api/method/intelligent_ordering.api.administration.`:

| Method | Purpose | Access |
| --- | --- | --- |
| `dashboard` | Business, inventory, and delivery counts | Store, finance, inventory, or delivery staff |
| `sales_analytics` | Daily/weekly/monthly/yearly verified sales and product/category/area breakdowns | Store or finance staff |
| `filter_options` | Product and category selectors | Store or finance staff |
| `list_customers` / `customer_activity` | Customer profiles and order history; financial aggregates omitted for Support | Store staff and Customer Support |
| `product_performance` | Product units and item sales from paid orders | Store staff |
| `admin_order_detail` | Order snapshots plus payment and delivery history | Store staff |
| `audit_events` | Search administrative audit history | System Manager, Business Admin, Store Manager |
| `management_activity` | Stock alerts, product/rider performance and staff activity | System Manager, Business Admin, Store Manager |
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
Catalog and category editing uses `/dashboard/products` with the existing
Product and Product Category DocTypes and native permissions.
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
Dashboard staff-activity previews show at most five events. The store audit
browser defaults to five entries per page; select 50 and submit the search to
browse more, or follow the full-history link to Frappe Desk. Pagination and
search retain access to older records without loading the complete log at once.

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
