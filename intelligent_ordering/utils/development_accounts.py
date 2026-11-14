import getpass
import ipaddress
from urllib.parse import urlsplit

import frappe


TEST_ACCOUNTS = (
    ("admin.test@smarto.local", "Test Administrator", "System Manager"),
    ("manager.test@smarto.local", "Test Manager", "Store Manager"),
    ("orders.test@smarto.local", "Test Orders", "Order Manager"),
    ("inventory.test@smarto.local", "Test Inventory", "Inventory Manager"),
    ("delivery.test@smarto.local", "Test Delivery Manager", "Delivery Manager"),
    ("finance.test@smarto.local", "Test Finance", "Finance Manager"),
    ("support.test@smarto.local", "Test Support", "Customer Support"),
    ("rider.test@smarto.local", "Test Rider", "Delivery Staff"),
)


def _account_roles(role):
    return ("System Manager", "Business Admin") if role == "System Manager" else (role,)


def _local_host(value):
    host = urlsplit(value if "://" in value else f"//{value}").hostname
    if not host:
        return False
    if host == "localhost" or host.endswith((".localhost", ".local", ".test")):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return (
        address.is_private
        and not address.is_unspecified
        and not address.is_multicast
        and not address.is_link_local
    )


def _require_local_development():
    site = frappe.local.site
    if frappe.conf.get("developer_mode") not in (1, "1"):
        frappe.throw("Test accounts require a developer-mode site.", frappe.ValidationError)
    if not _local_host(frappe.conf.get("host_name") or site):
        frappe.throw("Test accounts require a local/private site hostname.", frappe.ValidationError)
    if frappe.session.user != "Administrator" and "System Manager" not in frappe.get_roles():
        frappe.throw("A System Manager must provision test users.", frappe.PermissionError)
    confirmation = input(f"Confirm this site is NOT publicly accessible: enter LOCAL-ONLY {site}: ")
    if confirmation != f"LOCAL-ONLY {site}":
        frappe.throw("Local-only site confirmation was not provided.", frappe.ValidationError)


def provision():
    """Create local test users through Bench only; never expose as an API."""
    return _provision(TEST_ACCOUNTS, "System User")


def provision_customer():
    """Create the requested Website User using a hidden password prompt."""
    return _provision(
        (("customer.test@smarto.local", "SmartO Test Customer", "Customer"),), "Website User"
    )


def _provision(accounts, user_type):
    _require_local_development()
    pending = []
    result = []
    for email, full_name, role in accounts:
        expected_roles = _account_roles(role)
        for expected_role in expected_roles:
            if not frappe.db.exists("Role", expected_role):
                frappe.throw(f"Role {expected_role} is missing. Run migrate first.", frappe.ValidationError)
        if frappe.db.exists("User", email):
            user = frappe.get_doc("User", email)
            roles = {row.role for row in user.roles}
            if not user.enabled or user.user_type != user_type or roles != set(expected_roles) or user.role_profile_name:
                frappe.throw(
                    f"Existing test user {email} has conflicting roles or account settings; review it in Desk.",
                    frappe.ValidationError,
                )
            result.append({"email": email, "roles": expected_roles, "status": "existing; password unchanged"})
        else:
            pending.append((email, full_name, role))

    if not pending:
        return result
    password = getpass.getpass("Temporary password for NEW local test users: ")
    if not password or password != getpass.getpass("Confirm temporary password: "):
        frappe.throw("A non-empty matching password is required.", frappe.ValidationError)

    savepoint = "smarto_development_accounts"
    frappe.db.savepoint(savepoint)
    try:
        for email, full_name, role in pending:
            frappe.get_doc({
                "doctype": "User",
                "email": email,
                "first_name": full_name,
                "enabled": 1,
                "user_type": user_type,
                "send_welcome_email": 0,
                "new_password": password,
                "roles": [{"role": value} for value in _account_roles(role)],
            }).insert()
            result.append({"email": email, "roles": _account_roles(role), "status": "created"})
    except Exception:
        frappe.db.rollback(save_point=savepoint)
        raise
    return result


def verify_customer():
    """Verify the local customer's actual HTTP login and read-access boundaries."""
    import requests

    _require_local_development()
    base_url = input("Exact local site base URL (including the Bench port): ").rstrip("/")
    url = urlsplit(base_url)
    if (
        url.scheme not in {"http", "https"} or not _local_host(base_url)
        or url.username or url.password or url.path or url.query or url.fragment
    ):
        frappe.throw("Use a local/private HTTP(S) site base URL.", frappe.ValidationError)
    email = "customer.test@smarto.local"
    checks = []

    def record(label, passed):
        checks.append({"check": label, "status": "PASS" if passed else "FAIL"})

    original_user = frappe.session.user
    try:
        with requests.Session() as session:
            session.trust_env = False
            password = getpass.getpass(f"Local password for {email}: ")
            login = session.post(
                f"{base_url}/api/method/login", data={"usr": email, "pwd": password},
                timeout=30, allow_redirects=False,
            )
            identity = session.get(
                f"{base_url}/api/method/intelligent_ordering.api.v1.current_user",
                timeout=30, allow_redirects=False,
            )
            identity.raise_for_status()
            payload = identity.json().get("message", {})
            authenticated = login.status_code == 200 and payload.get("user") == email
            record("Actual independent Frappe HTTP login", authenticated)
            if not authenticated:
                return {"all_passed": False, "checks": checks}
            record("Customer-only roles",
                   set(payload.get("roles", [])) - {"All", "Guest"} == {"Customer"})
            for endpoint in (
                "customers.get_profile", "customers.list_addresses", "customers.payment_history",
                "customers.notifications", "orders.get_my_orders",
            ):
                response = session.get(
                    f"{base_url}/api/method/intelligent_ordering.api.{endpoint}",
                    timeout=30, allow_redirects=False,
                )
                record(f"HTTP {endpoint}", response.status_code == 200)
            for endpoint in ("orders.list_orders", "payments.list_transactions", "inventory.get_dashboard",
                             "deliveries.list_deliveries", "administration.sales_analytics"):
                response = session.get(
                    f"{base_url}/api/method/intelligent_ordering.api.{endpoint}",
                    timeout=30, allow_redirects=False,
                )
                record(f"HTTP {endpoint} denied", response.status_code == 403)
            from intelligent_ordering.utils.staff_pages import PAGE_ROLES
            for page in PAGE_ROLES:
                response = session.get(
                    f"{base_url}/dashboard/{page}", timeout=30, allow_redirects=False,
                )
                record(f"HTTP dashboard/{page} denied", response.status_code == 403)
            frappe.set_user(email)
            record("User creation denied", not frappe.has_permission("User", "create"))
            for doctype in ("Role", "Sales Order", "Payment Transaction"):
                record(f"{doctype} mutation denied", not frappe.has_permission(doctype, "write"))
            other_orders = frappe.db.sql(
                """SELECT o.name FROM `tabSales Order` o
                   INNER JOIN `tabCustomer Profile` c ON c.name = o.customer
                   WHERE c.user != %s LIMIT 1""", email, as_dict=True,
            )
            if other_orders:
                for endpoint in ("orders.get_my_order", "customers.track_order", "payments.get_order_payments"):
                    response = session.get(
                        f"{base_url}/api/method/intelligent_ordering.api.{endpoint}",
                        params={"order_name": other_orders[0].name},
                        timeout=30, allow_redirects=False,
                    )
                    record(f"HTTP other customer {endpoint} denied", response.status_code == 403)
            else:
                checks.append({"check": "Other-customer order/payment HTTP denial",
                               "status": "NOT TESTED: requires an existing other-customer order"})
    finally:
        frappe.set_user(original_user)
    return {"all_passed": all(row["status"] == "PASS" for row in checks), "checks": checks}


def verify():
    """Check actual local logins and permissions without creating business records."""
    import requests

    _require_local_development()
    base_url = input("Exact local site base URL (including the Bench port): ").rstrip("/")
    url = urlsplit(base_url)
    if url.scheme not in {"http", "https"} or not _local_host(base_url) or url.username or url.password:
        frappe.throw("Verification requires a local/private HTTP(S) URL.", frappe.ValidationError)
    if url.path or url.query or url.fragment:
        frappe.throw("Use a site base URL without a path or query.", frappe.ValidationError)

    from intelligent_ordering.api import orders, payments
    from intelligent_ordering.utils.staff_pages import PAGE_ROLES, require_staff_page

    checks = []
    original_user = frappe.session.user
    read_endpoints = {
        "System Manager": ("orders.list_orders", "inventory.list_product_options",
                           "deliveries.delivery_dashboard", "payments.list_transactions",
                           "administration.sales_analytics"),
        "Store Manager": ("orders.list_orders", "deliveries.delivery_dashboard",
                          "administration.sales_analytics"),
        "Order Manager": ("orders.list_orders", "deliveries.delivery_dashboard"),
        "Inventory Manager": ("inventory.list_product_options", "inventory.get_dashboard"),
        "Delivery Manager": ("deliveries.delivery_dashboard", "deliveries.list_deliveries"),
        "Finance Manager": ("payments.list_transactions", "administration.sales_analytics"),
        "Customer Support": ("orders.list_orders",),
        "Delivery Staff": ("deliveries.list_deliveries",),
    }

    def record(email, check, passed):
        checks.append({"email": email, "check": check, "status": "PASS" if passed else "FAIL"})

    def denied(email, label, operation):
        try:
            operation()
        except frappe.PermissionError:
            record(email, label, True)
        else:
            record(email, label, False)

    try:
        for email, _, role in TEST_ACCOUNTS:
            expected_roles = set(_account_roles(role))
            with requests.Session() as session:
                session.trust_env = False
                password = getpass.getpass(f"Local password for {email}: ")
                try:
                    login = session.post(
                        f"{base_url}/api/method/login",
                        data={"usr": email, "pwd": password},
                        timeout=30, allow_redirects=False,
                    )
                    identity = session.get(
                        f"{base_url}/api/method/intelligent_ordering.api.v1.current_user",
                        timeout=30, allow_redirects=False,
                    )
                    payload = identity.json().get("message", {})
                    authenticated = (
                        login.status_code == 200 and identity.status_code == 200
                        and isinstance(payload, dict) and payload.get("user") == email
                    )
                    record(email, "Independent HTTP login", authenticated)
                    if not authenticated:
                        continue
                    actual_roles = set(payload.get("roles", []))
                    record(email, "Exact app roles", actual_roles - {"All", "Guest", "Desk User"} == expected_roles)
                    for endpoint in read_endpoints[role]:
                        response = session.get(
                            f"{base_url}/api/method/intelligent_ordering.api.{endpoint}",
                            timeout=30, allow_redirects=False,
                        )
                        record(email, f"HTTP {endpoint}", response.status_code == 200)
                    for page, page_roles in PAGE_ROLES.items():
                        allowed = bool(expected_roles & page_roles)
                        response = session.get(
                            f"{base_url}/dashboard/{page}", timeout=30, allow_redirects=False,
                        )
                        record(email, f"HTTP dashboard/{page}",
                               response.status_code == 200 if allowed else response.status_code == 403)
                    if role in {"Inventory Manager", "Customer Support", "Delivery Manager", "Delivery Staff"}:
                        response = session.get(
                            f"{base_url}/api/method/intelligent_ordering.api.payments.list_transactions",
                            timeout=30, allow_redirects=False,
                        )
                        record(email, "HTTP payment transactions denied", response.status_code == 403)

                    frappe.set_user(email)
                    if role != "System Manager":
                        record(email, "System configuration mutation denied",
                               not frappe.has_permission("System Settings", "write"))
                        record(email, "User provisioning denied",
                               not frappe.has_permission("User", "create"))
                    if role in {"Inventory Manager", "Customer Support", "Delivery Manager", "Delivery Staff"}:
                        record(email, "Payment Transaction DocType read denied",
                               not frappe.has_permission("Payment Transaction", "read"))
                    for page, page_roles in PAGE_ROLES.items():
                        if not expected_roles.intersection(page_roles):
                            denied(email, f"Server dashboard/{page}",
                                   lambda page=page: require_staff_page(frappe._dict(), page))
                    if role not in {"System Manager", "Store Manager", "Order Manager"}:
                        denied(email, "Server order mutation denied",
                               lambda: orders.update_order_status("LOCAL-PERMISSION-CHECK", "Confirmed"))
                    if role not in {"System Manager", "Finance Manager"}:
                        denied(email, "Server finance reconciliation denied",
                               lambda: payments.reconcile_payment("LOCAL-PERMISSION-CHECK"))
                    if role == "Inventory Manager":
                        record(email, "Product create/edit permitted",
                               bool(frappe.has_permission("Product", "create")
                                    and frappe.has_permission("Product", "write")))
                    if role == "Customer Support":
                        for doctype in ("Customer Profile", "Sales Order"):
                            record(email, f"{doctype} read-only",
                                   bool(frappe.has_permission(doctype, "read")
                                        and not frappe.has_permission(doctype, "write")
                                        and not frappe.has_permission(doctype, "create")))
                    if role == "Delivery Staff":
                        response = session.get(
                            f"{base_url}/api/method/intelligent_ordering.api.deliveries.list_deliveries",
                            timeout=30, allow_redirects=False,
                        )
                        listing = response.json().get("message", {})
                        record(email, "HTTP assigned delivery listing",
                               response.status_code == 200 and isinstance(listing, dict)
                               and isinstance(listing.get("deliveries"), list)
                               and all(row["assigned_delivery_person"] == email
                                       for row in listing.get("deliveries", [])))
                        if isinstance(listing, dict) and not listing.get("deliveries"):
                            checks.append({"email": email, "check": "View assigned delivery",
                                           "status": "NOT TESTED: no assigned delivery fixture"})
                        other_delivery = frappe.get_all(
                            "Delivery", filters={"assigned_delivery_person": ["!=", email]},
                            fields=["name"], limit_page_length=1,
                        )
                        if other_delivery:
                            response = session.get(
                                f"{base_url}/api/method/intelligent_ordering.api.deliveries.get_delivery",
                                params={"delivery_name": other_delivery[0].name},
                                timeout=30, allow_redirects=False,
                            )
                            record(email, "HTTP unassigned delivery denied", response.status_code == 403)
                        else:
                            checks.append({"email": email, "check": "HTTP unassigned delivery denied",
                                           "status": "NOT TESTED: no unassigned delivery fixture"})
                except (requests.RequestException, ValueError) as error:
                    checks.append({"email": email, "check": "HTTP verification",
                                   "status": f"FAIL: {type(error).__name__}"})
                finally:
                    password = None
                    frappe.set_user(original_user)
    finally:
        frappe.set_user(original_user)
    return {"all_passed": all(row["status"] == "PASS" for row in checks), "checks": checks}
