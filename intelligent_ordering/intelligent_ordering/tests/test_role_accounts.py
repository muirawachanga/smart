from html.parser import HTMLParser

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils.password import check_password

from intelligent_ordering.api import administration, deliveries, inventory, orders, payments
from intelligent_ordering.install import APP_ROLES, ensure_roles
from intelligent_ordering.utils.development_accounts import TEST_ACCOUNTS, _account_roles
from intelligent_ordering.utils.staff_pages import require_staff_page


class NavigationLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = {}

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "a" and "id" in attributes:
            self.links[attributes["id"]] = attributes


class TestRoleAccounts(FrappeTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        self.password = f"Role-Test-{frappe.generate_hash(length=24)}!9"
        self.users = {}
        suffix = frappe.generate_hash(length=8)
        for email, full_name, role in TEST_ACCOUNTS:
            user = frappe.get_doc({
                "doctype": "User",
                "email": f"{email.split('@')[0]}-{suffix}@example.test",
                "first_name": full_name,
                "enabled": 1,
                "user_type": "System User" if role == "System Manager" or APP_ROLES[role] else "Website User",
                "send_welcome_email": 0,
                "new_password": self.password,
                "roles": [{"role": value} for value in _account_roles(role)],
            }).insert()
            self.users[role] = user.name

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def test_each_role_has_an_independent_password_backed_frappe_user(self):
        for role, user in self.users.items():
            with self.subTest(role=role):
                self.assertEqual(check_password(user, self.password), user)
                frappe.set_user(user)
                expected_type = "System User" if role == "System Manager" or APP_ROLES[role] else "Website User"
                self.assertEqual(frappe.db.get_value("User", user, "user_type"), expected_type)
                self.assertEqual("Desk User" in frappe.get_roles(), expected_type == "System User")
                if role != "System Manager":
                    self.assertNotIn("System Manager", frappe.get_roles())
                    self.assertFalse(frappe.has_permission("User", "create"))

    def test_role_migration_downgrades_existing_staff_without_removing_roles_or_custom_desk_grants(self):
        role = frappe.get_doc("Role", "Inventory Manager")
        role.desk_access = 1
        role.save()
        user = self.users["Inventory Manager"]
        self.assertEqual(frappe.db.get_value("User", user, "user_type"), "System User")
        mixed = frappe.get_doc({
            "doctype": "User", "email": f"mixed-{frappe.generate_hash(length=8)}@example.test",
            "first_name": "Mixed roles", "enabled": 1, "send_welcome_email": 0,
            "roles": [{"role": "Inventory Manager"}, {"role": "Finance Manager"}],
        }).insert()
        ensure_roles()
        self.assertEqual(frappe.db.get_value("User", user, "user_type"), "Website User")
        self.assertEqual(frappe.db.get_value("User", mixed.name, "user_type"), "System User")
        self.assertIn("Finance Manager", frappe.get_roles(mixed.name))
        frappe.set_user(user)
        self.assertIn("Inventory Manager", frappe.get_roles())
        self.assertNotIn("Desk User", frappe.get_roles())
        self.assertTrue(frappe.has_permission("Product", "create"))
        require_staff_page(frappe._dict(), "inventory")
        inventory.get_dashboard()

    def test_website_staff_sidebars_do_not_point_to_desk(self):
        for role, page in (
            ("Store Manager", "owner"), ("Order Manager", "orders"),
            ("Inventory Manager", "inventory"), ("Delivery Manager", "delivery"),
            ("Delivery Staff", "delivery"), ("Customer Support", "support"),
        ):
            frappe.set_user(self.users[role])
            context = frappe._dict()
            require_staff_page(context, page)
            parser = NavigationLinks()
            parser.feed(frappe.render_template("templates/includes/staff_sidebar.html", context))
            for attributes in parser.links.values():
                if "hidden" not in attributes:
                    with self.subTest(role=role, link=attributes["id"]):
                        self.assertFalse(attributes["href"].startswith("/app/"))

    def test_admin_sidebar_renders_every_shortcut_visible_without_browser_scripts(self):
        for user in ("Administrator", self.users["System Manager"]):
            frappe.set_user(user)
            context = frappe._dict()
            require_staff_page(context, "admin")
            parser = NavigationLinks()
            parser.feed(frappe.render_template("templates/includes/staff_sidebar.html", context))
            for link in context.smarto_visible_staff_links:
                with self.subTest(user=user, link=link):
                    self.assertNotIn("hidden", parser.links[link])
            self.assertEqual(parser.links["staff-delivery-areas-link"]["href"], "/dashboard/delivery-areas")
            self.assertEqual(parser.links["payments-link"]["href"], "/dashboard/sales#payment-dashboard")

    def test_support_is_read_only_and_cannot_access_other_workspaces_or_payments(self):
        frappe.set_user(self.users["Customer Support"])
        require_staff_page(frappe._dict(), "support")
        orders.list_orders()
        administration.list_customers()
        self.assertTrue(frappe.has_permission("Customer Profile", "read"))
        self.assertTrue(frappe.has_permission("Sales Order", "read"))
        for doctype in ("Customer Profile", "Sales Order"):
            self.assertFalse(frappe.has_permission(doctype, "write"))
            self.assertFalse(frappe.has_permission(doctype, "create"))
        for page in ("admin", "orders", "inventory", "delivery", "sales"):
            with self.subTest(page=page), self.assertRaises(frappe.PermissionError):
                require_staff_page(frappe._dict(), page)
        with self.assertRaises(frappe.PermissionError):
            orders.update_order_status("ROLE-TEST-NONEXISTENT", "Confirmed")
        with self.assertRaises(frappe.PermissionError):
            payments.list_transactions()
        with self.assertRaises(frappe.PermissionError):
            payments.reconcile_payment("ROLE-TEST-NONEXISTENT")
        with self.assertRaises(frappe.PermissionError):
            administration.management_activity()
        self.assertEqual(frappe.get_list("Shopping Cart"), [])

    def test_inventory_can_create_and_edit_products_without_financial_access(self):
        frappe.set_user(self.users["Inventory Manager"])
        product = frappe.get_doc({
            "doctype": "Product",
            "sku": f"ROLE-{frappe.generate_hash(length=8)}",
            "product_name": "Role permission test product",
            "price": 25,
            "currency": "KES",
            "enabled": 1,
        }).insert()
        product.product_name = "Updated role permission test product"
        product.save()
        self.assertEqual(frappe.db.get_value("Product", product.name, "product_name"), product.product_name)
        inventory.list_product_options(search=product.sku)
        with self.assertRaises(frappe.PermissionError):
            payments.list_transactions()
        with self.assertRaises(frappe.PermissionError):
            payments.reconcile_payment("ROLE-TEST-NONEXISTENT")
        self.assertFalse(frappe.has_permission("Payment Transaction", "read"))

    def test_only_admin_and_finance_roles_can_reconcile_payments(self):
        for role in ("Store Manager", "Order Manager", "Inventory Manager",
                     "Delivery Manager", "Customer Support", "Delivery Staff"):
            frappe.set_user(self.users[role])
            with self.subTest(role=role), self.assertRaises(frappe.PermissionError):
                payments.reconcile_payment("ROLE-TEST-NONEXISTENT")

    def test_forecast_roles_cannot_cross_finance_and_inventory_boundaries(self):
        frappe.set_user(self.users["Inventory Manager"])
        administration.demand_forecast()
        with self.assertRaises(frappe.PermissionError):
            administration.sales_forecast()
        frappe.set_user(self.users["Finance Manager"])
        administration.sales_forecast()
        administration.demand_forecast()
        for role in ("Customer Support", "Delivery Manager", "Delivery Staff"):
            frappe.set_user(self.users[role])
            with self.subTest(role=role), self.assertRaises(frappe.PermissionError):
                administration.sales_forecast()
            with self.subTest(role=role), self.assertRaises(frappe.PermissionError):
                administration.demand_forecast()

    def test_rider_cannot_manage_orders_or_deliveries_for_another_person(self):
        frappe.set_user(self.users["Delivery Staff"])
        listing = deliveries.list_deliveries()
        self.assertTrue(all(row.assigned_delivery_person == frappe.session.user
                            for row in listing["deliveries"]))
        with self.assertRaises(frappe.PermissionError):
            deliveries._check_assigned(frappe._dict(assigned_delivery_person=self.users["Delivery Manager"]))
        with self.assertRaises(frappe.PermissionError):
            deliveries._require_manager()
        with self.assertRaises(frappe.PermissionError):
            orders.list_orders()
        with self.assertRaises(frappe.PermissionError):
            orders.update_order_status("ROLE-TEST-NONEXISTENT", "Confirmed")
