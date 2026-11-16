from collections.abc import Mapping
from urllib.parse import urlparse

import frappe

from intelligent_ordering.api.policies import POLICIES, current_policy
from intelligent_ordering.utils.business import BUSINESS_FIELDS, get_business_profile, validate_profile
from intelligent_ordering.utils.mpesa import DarajaClient


MANUAL_CHECKS = (
    ("workflows", "Verify ordering and every staff role",
     "On an isolated test site, exercise checkout, stock, delivery, denied actions and customer isolation."),
    ("providers", "Verify payment and optional providers",
     "Test successful, failed, pending and duplicate payment callbacks and reconciliation; verify SMS/Gemini if enabled."),
    ("recovery", "Verify backups and restoration",
     "Schedule per-site backups and restore one into an isolated site; record the recovery procedure."),
    ("operations", "Verify infrastructure and monitoring",
     "Verify public HTTPS, DNS/site routing, workers, scheduler activity, alerts and restricted/redacted logs."),
    ("isolation", "Verify separate-business isolation",
     "Test account, database, file, cookie and backup isolation between separately configured sites."),
    ("policies", "Review legal, privacy and support commitments",
     "Approve policies, data retention/deletion, provider data handling and your actual customer support process."),
)


def _require_admin(write=False):
    user = frappe.session.user
    roles = set(frappe.get_roles(user))
    allowed = {"System Manager"} if write else {"System Manager", "Business Admin"}
    if user == "Guest" or (user != "Administrator" and not roles.intersection(allowed)):
        frappe.throw("You are not authorized to manage business onboarding.", frappe.PermissionError)


@frappe.whitelist(methods=["POST"])
def save_business(name, email="", phone="", address=""):
    _require_admin(write=True)
    if not all(frappe.get_meta("Website Settings").has_field(field) for field in BUSINESS_FIELDS.values()):
        frappe.throw("Run the site migration before saving business details.", frappe.ValidationError)
    try:
        profile = validate_profile({"name": name, "email": email, "phone": phone, "address": address})
    except ValueError as error:
        frappe.throw(str(error), frappe.ValidationError)
    settings = frappe.get_doc("Website Settings")
    for key, field in BUSINESS_FIELDS.items():
        settings.set(field, profile[key])
    settings.save(ignore_permissions=True)
    return {"business": get_business_profile()}


@frappe.whitelist()
def readiness():
    _require_admin()
    profile = get_business_profile()
    checks = []

    def check(key, title, passed, detail, link):
        checks.append({
            "key": key, "title": title, "status": "configured" if passed else "blocked",
            "detail": detail, "link": link,
        })

    migrated = all(frappe.get_meta("Website Settings").has_field(field) for field in BUSINESS_FIELDS.values())
    check("migration", "Business settings schema", migrated,
          "Run bench --site <site-name> migrate after updating the app.", "/app/website-settings")
    try:
        validate_profile(profile)
        identity = True
    except ValueError:
        identity = False
    check("identity", "Public business identity and support contact", identity,
          "Save a business name and at least one reachable public support contact.", "/dashboard/setup")
    for kind, title in POLICIES.items():
        check(f"policy_{kind}", title, bool(current_policy(kind)),
              "Publish approved policy text; publication alone does not verify legal adequacy.",
              "/app/smarto-policy-version")

    catalog = frappe.db.sql("""
        SELECT COUNT(*) FROM `tabProduct` p
        INNER JOIN `tabProduct Category` c ON c.name = p.category AND c.enabled = 1
        WHERE p.enabled = 1
    """)[0][0]
    stock = frappe.db.sql("""
        SELECT COUNT(*) FROM (
            SELECT b.product FROM `tabStock Balance` b
            INNER JOIN `tabStock Warehouse` w ON w.name = b.warehouse AND w.status = 'Active'
            INNER JOIN `tabProduct` p ON p.name = b.product AND p.enabled = 1
            INNER JOIN `tabProduct Category` c ON c.name = p.category AND c.enabled = 1
            GROUP BY b.product HAVING SUM(b.available_quantity) > 0
        ) available
    """)[0][0]
    missing_areas = frappe.db.sql("""
        SELECT COUNT(*) FROM `tabProduct` p
        INNER JOIN `tabProduct Category` c ON c.name = p.category AND c.enabled = 1
        WHERE p.enabled = 1 AND NOT EXISTS (
            SELECT 1 FROM `tabDelivery Area` a WHERE a.enabled = 1 AND a.currency = p.currency
        )
    """)[0][0]
    check("catalog", "Published product catalog", bool(catalog),
          "Create enabled products in enabled categories with accurate prices and currencies.", "/app/product")
    check("stock", "Saleable stock", bool(stock),
          "Receive stock through the inventory workflow in an active warehouse.", "/dashboard/inventory")
    check("areas", "Delivery areas for catalog currencies", bool(catalog) and not missing_areas,
          "Enable a delivery area with a fee for every currency used by published products.", "/app/delivery-area")
    staff = frappe.db.sql("""
        SELECT COUNT(DISTINCT u.name) FROM `tabUser` u
        INNER JOIN `tabHas Role` r ON r.parent = u.name AND r.parenttype = 'User'
        WHERE u.enabled = 1 AND u.name NOT IN ('Administrator', 'Guest')
          AND u.user_type = 'System User'
          AND r.role IN ('Business Admin', 'Store Manager', 'Order Manager', 'Inventory Manager',
                         'Finance Manager', 'Delivery Manager', 'Delivery Staff', 'Customer Support')
    """)[0][0]
    check("staff", "Named staff accounts", bool(staff),
          "Create individual staff accounts with least-privilege roles; test each required role.", "/app/user")

    host = frappe.conf.get("host_name")
    try:
        host_url = urlparse(host) if isinstance(host, str) else urlparse("")
    except ValueError:
        host_url = urlparse("")
    https = bool(host_url.scheme == "https" and host_url.hostname and not host_url.username
                 and not host_url.password and not host_url.query and not host_url.fragment
                 and host_url.path in ("", "/"))
    check("https", "Configured HTTPS site origin", https,
          "Set host_name to the business's HTTPS origin; verify certificate and public routing separately.",
          "/app/system-settings")
    check("developer", "Developer mode disabled", not frappe.conf.get("developer_mode"),
          "Disable developer_mode on the production site; do not disable it merely to pass a development check.",
          "/app/system-settings")
    scheduler = frappe.db.get_single_value("System Settings", "enable_scheduler")
    check("scheduler", "Scheduler enabled in configuration",
          bool(scheduler) and not any(frappe.conf.get(key) for key in
                                     ("pause_scheduler", "disable_scheduler", "maintenance_mode")),
          "Enable the site scheduler and verify actual worker/scheduler activity separately.", "/app/system-settings")

    mpesa = frappe.conf.get("mpesa")
    payment_valid = False
    if isinstance(mpesa, Mapping):
        try:
            DarajaClient(mpesa)
            callback = urlparse(mpesa.get("callback_url", ""))
            payment_valid = (
                mpesa.get("environment", "Sandbox") == "Production" and https
                and callback.netloc == host_url.netloc
                and callback.path == "/api/method/intelligent_ordering.api.payments.callback"
            )
        except ValueError:
            payment_valid = False
    check("payments", "Production M-Pesa configuration", payment_valid,
          "Set private production credentials and the callback on this site's HTTPS origin. "
          "Configuration checks do not verify credentials, account approval or callback reachability.",
          "/dashboard/sales")

    optional = []
    for key, label in (("fulfillment_notifications", "Africa's Talking SMS"), ("gemini", "Gemini assistance")):
        config = frappe.conf.get(key)
        optional.append({
            "title": label,
            "status": "enabled; requires provider verification" if isinstance(config, Mapping) and config.get("enabled")
            else "disabled or unconfigured",
        })
    return {
        "business": profile, "checks": checks, "optional": optional,
        "blocking_count": sum(item["status"] == "blocked" for item in checks),
        "manual_checks": [{"key": key, "title": title, "detail": detail, "status": "not_verified"}
                          for key, title, detail in MANUAL_CHECKS],
        "notice": "Configuration checks only. This report never certifies production readiness. "
                  "Manual checks are not verified or marked complete by this workspace.",
    }
