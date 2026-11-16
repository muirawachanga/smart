# SmartO

SmartO is a Frappe-based ordering and fulfillment application for businesses
managing customer orders, inventory, M-Pesa payments and deliveries. It provides
customer shopping pages, role-based staff workspaces, optional Gemini shopping
assistance, Africa's Talking SMS integration and database-backed reporting.

**Deployment status:** Commercial foundation in development. Application code
and standalone tests do not establish production readiness. Frappe/database
integration, live providers, business isolation and recovery must be verified
on the actual deployment before accepting real customer data or payments.

## Documentation

- [Quick start](#quick-start)
- [Business onboarding](#business-onboarding)
- [Features and boundaries](#features-and-boundaries)
- [User workspaces](#user-workspaces)
- [Architecture](#architecture)
- [Commercial launch checklist](#commercial-launch-checklist)
- [Development and operations guide](docs/DEVELOPMENT.md)

## Quick start

Use an existing Frappe Bench environment with Python, Node.js, Redis, MariaDB
and a created site. Select, verify and record compatible Frappe/Bench versions;
this repository does not currently pin them.

From the Bench directory, replace the placeholders:

```bash
bench get-app intelligent_ordering <repository-url>
bench --site <site-name> install-app intelligent_ordering
bench --site <site-name> migrate
bench build --app intelligent_ordering
bench start
```

`bench start` is a development server, not a production hosting setup.
Visit `/products` for the storefront and sign in as a System Manager to open
`/dashboard/setup`. See the [installation guide](docs/DEVELOPMENT.md#install-the-app)
for a local-checkout installation.

For an existing installation, back up the site, deploy the updated app, run
`bench --site <site-name> migrate`, rebuild assets and clear the site cache.
Rehearse upgrades and restoration on staging before production.

## Business onboarding

Use **Administrator dashboard -> Business setup and launch checks**:

1. As a System Manager, save the public business name, support email/phone and
   business address. These are stored on the existing Website Settings record,
   appear on the storefront/contact page and are audited when changed.
2. Create enabled categories and products with correct prices and currencies.
   Create an active warehouse and receive opening stock using the inventory
   workflow.
3. Configure delivery areas and fees for every catalog currency.
4. Create named staff accounts with least-privilege roles and publish approved
   Terms, Privacy, Refund and Delivery policies.
5. Configure private provider credentials and production infrastructure, then
   review the automated blockers and complete the separate manual checks.

Business Admins can view the setup report; saving public identity through the
workspace requires System Manager. Existing Frappe permissions still control
Desk tools. The report checks database/configuration state, makes no provider
calls, and cannot certify that credentials, staff workflows or infrastructure
actually work.

For bulk master data, use the standard Frappe Data Import tool with its supported
templates and test a small import first. Receive stock through inventory APIs;
do not import stock balances, payment success states or order transitions to
bypass application workflows.

### Separate businesses

Deploy **one Frappe site with its own database per business**. Configure users,
catalog, policies, delivery areas and provider credentials separately. This is
a managed-store deployment model, not a shared marketplace or cross-business
checkout. Follow the [business isolation guide](docs/DEVELOPMENT.md#multiple-businesses-one-site-per-business)
and verify actual host, database, account, cookie, storage and backup isolation.

### Secrets and providers

Keep credentials in the site's private `sites/<site-name>/site_config.json`.
Never commit this file or send credentials through customer forms.
`.env.example` is reference only and is not automatically loaded by Frappe.

| Integration | Setup guide | Important boundary |
| --- | --- | --- |
| M-Pesa Daraja | [Payment configuration](docs/DEVELOPMENT.md#m-pesa-configuration-and-operations) | Configure this business's HTTPS callback; pending payments are not revenue |
| Africa's Talking | [SMS configuration](docs/DEVELOPMENT.md#africas-talking-sms) | Requires scheduler/workers; provider acceptance is not handset delivery |
| Gemini | [Assistant configuration](docs/DEVELOPMENT.md#gemini-shopping-assistant) | Optional and consent-based; do not enter sensitive data |

## Features and boundaries

Implemented means code exists, not that live operation has been verified.

| Area | Available functionality | Boundary / remaining work |
| --- | --- | --- |
| Ordering | Catalog, cart, authenticated checkout, customer history and validated staff transitions | Exercise complete database-backed workflows before launch |
| Inventory | Balances, reservations, movements and authorized stock adjustments | No automatic predictive replenishment |
| Payments | M-Pesa integration, transaction reporting and provider-backed reconciliation | Verify sandbox/live outcomes; refund-request/approval workflows remain future work |
| SMS | Order, payment and delivery events through the existing notification outbox | No handset delivery receipts; investigate ambiguous outcomes before resending |
| Delivery | Role-scoped assignments, status actions and proximity-based group planning | Straight-line estimates, not road navigation, continuous GPS or traffic-aware routing |
| Assistance | Gemini product assistance and validated suggestions | Customer must explicitly add products and finish normal checkout; no AI-controlled payments |
| Recommendations | Signed-in customer's completed-order history and available products | Not a trained collaborative-filtering or XGBoost model |
| Forecasts | Local weekday-seasonal statistical sales/demand estimates | Requires sufficient history; estimates are not guarantees |
| Administration | Reporting, role-protected workspaces and append-only administrative audit events | Validate permissions and operational coverage on the installed site |
| Business setup | Site-specific public identity, setup links and configuration checks | Not subscription billing, automatic site provisioning or production certification |

Complaint escalation, refund/return approval lifecycles, delivery OTP/customer
confirmation, client subscription billing and automated monitoring/backup
operations are not delivered by the setup workspace. Voice ordering, alternative
AI providers, dynamic pricing and advanced machine-learning models are also
outside the current scope.

## User workspaces

| User | Entry point | Responsibility |
| --- | --- | --- |
| Customer | `/products`, `/assistant`, `/account` | Shopping and owner-scoped order history |
| Rider (`Delivery Staff`) | `/dashboard/delivery` | Their assigned deliveries and permitted status actions, not financial management |
| Delivery Manager | `/dashboard/delivery` | Assignment, monitoring and delivery planning |
| Finance Manager | `/dashboard/sales` | Reporting, reconciliation and forecasts, not unrestricted payment editing |
| Inventory Manager | `/dashboard/inventory` | Stock operations, movement history and demand estimates |
| Order Manager | `/dashboard/orders` | Order search, details and validated status transitions |
| Customer Support | `/dashboard/support` | Read-only profiles, order history and enquiries |
| Store Manager | `/dashboard/owner` | Business reporting and authorized store operations |
| System Manager / Business Admin | `/dashboard/admin`, `/dashboard/setup` | Authorized administration and onboarding |

Page visibility does not grant API permission. Backend checks remain
authoritative, including for accounts with multiple roles. See the
[personnel guide](docs/DEVELOPMENT.md#personnel-accounts-and-workspaces) for
the access matrix and private development-account instructions.

## Architecture

SmartO uses native Frappe website routes, Python APIs and the existing site's
DocTypes. Its internal app/package name remains `intelligent_ordering`.

```text
Customer pages / staff workspaces
                |
       Validated Frappe APIs
                |
Product / Customer Profile / Shopping Cart
                |
       Sales Order + Sales Order Item
          |          |           |
 Payment Transaction |        Delivery + Delivery Activity
                     |
       Stock Balance / Stock Ledger Entry

Order/payment/delivery events -> Fulfillment Notification -> SMS scheduler
Administrative changes -> Admin Audit Log
Website Settings -> public business identity and contact information
Public catalog + consented conversation -> Gemini suggestions
Customer-scoped history -> recommendations
Authorized aggregate history -> local forecasts
```

This is a relationship overview, not a strictly sequential workflow. Payment,
stock and delivery changes retain their validated lifecycles. Gemini receives
no private customer profiles or payment records.

## Commercial launch checklist

- Rehearse checkout, confirmation, payment, stock allocation and delivery on
  an isolated test site. Test failure, cancellation, duplicate and retry paths.
- Verify each role's allowed and denied actions and customer/site isolation.
- Configure production HTTPS, DNS/site routing, secure authentication and
  site-specific credentials. Redact payment callback tokens from proxy logs.
- Apply migrations/assets and verify actual worker, scheduler and outbox activity.
- Test provider credentials and callbacks; verify optional SMS/Gemini operation,
  costs, consent and provider data handling before enabling them.
- Establish restricted logging, uptime/error alerts, per-site backups and a
  successfully tested restoration procedure.
- Approve business policies, support channels, privacy/retention procedures
  and applicable legal obligations. Obtain independent security review.
- Define pricing, service commitments, invoicing and business exit/data-export
  procedures. Client subscription automation is not yet implemented.

The setup page reports configuration blockers and lists manual verification
tasks. It never marks the business production-ready. Use a supervised pilot
before a broader commercial rollout, and do not provision development test
accounts on production.

## Validation

From a repository virtual environment with the app installed:

```bash
python -m unittest discover -s tests -v
node --test tests/frontend/*.test.js
```

From Bench with the app installed on an isolated test site:

```bash
bench --site <test-site-name> run-tests --app intelligent_ordering
```

Standalone tests are not substitutes for Frappe permissions, database lifecycle
tests, real browser acceptance, provider verification or a deployment review.
See [tests and checks](docs/DEVELOPMENT.md#tests-and-checks) for environment setup.
