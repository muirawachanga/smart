import unittest
from pathlib import Path

from intelligent_ordering.hooks import website_route_rules


APP_ROOT = Path(__file__).resolve().parents[1] / "intelligent_ordering"
WWW = APP_ROOT / "www"
SHELL_ROUTES = {
    "/": "index.html",
    "/about": "about.html",
    "/products": "products.html",
    "/categories": "categories.html",
    "/cart": "cart.html",
    "/checkout": "checkout.html",
    "/payment": "payment.html",
    "/track-order": "track-order.html",
    "/contact": "contact.html",
    "/register": "register.html",
    "/forgot-password": "forgot-password.html",
    "/reset-password": "reset-password.html",
    "/account": "account.html",
    "/account/profile": "account/profile.html",
    "/account/addresses": "account/addresses.html",
    "/account/payments": "account/payments.html",
    "/account/notifications": "account/notifications.html",
    "/dashboard/owner": "dashboard/owner.html",
    "/dashboard/admin": "dashboard/admin.html",
    "/dashboard/sales": "dashboard/sales.html",
    "/dashboard/orders": "dashboard/orders.html",
    "/dashboard/inventory": "dashboard/inventory.html",
    "/dashboard/delivery": "dashboard/delivery.html",
    "/dashboard/support": "dashboard/support.html",
}


class TestSmartOWebsiteRoutes(unittest.TestCase):
    def test_static_pages_use_the_shared_smarto_layout(self):
        for route, template in SHELL_ROUTES.items():
            with self.subTest(route=route):
                source = (WWW / template).read_text()
                self.assertIn(
                    '{% extends "templates/smarto_base.html" %}',
                    source,
                )

    def test_dynamic_routes_resolve_to_page_templates(self):
        expected = {
            ("/products/<product_id>", "product-details"),
            ("/order-confirmation/<order_id>", "order-confirmation"),
        }
        actual = {
            (rule["from_route"], rule["to_route"])
            for rule in website_route_rules
        }
        self.assertTrue(expected.issubset(actual))
        for _, template in expected:
            self.assertTrue((WWW / f"{template}.html").is_file())

    def test_customer_pages_load_their_scripts(self):
        expected = {
            "index.html": "catalog-pages.js",
            "products.html": "catalog-pages.js",
            "categories.html": "catalog-pages.js",
            "product-details.html": "catalog-pages.js",
            "cart.html": "cart-page.js",
            "checkout.html": "checkout-page.js",
            "order-confirmation.html": "order-confirmation.js",
            "payment.html": "order-confirmation.js",
            "account.html": "order-pages.js",
            "account/profile.html": "customer-portal.js",
            "account/addresses.html": "customer-portal.js",
            "account/payments.html": "customer-portal.js",
            "account/notifications.html": "customer-portal.js",
            "register.html": "customer-portal.js",
            "dashboard/orders.html": "order-pages.js",
            "dashboard/inventory.html": "inventory-page.js",
            "dashboard/delivery.html": "delivery-page.js",
            "dashboard/support.html": "order-pages.js",
        }
        for template, script in expected.items():
            with self.subTest(template=template):
                source = (WWW / template).read_text()
                self.assertIn(f"/assets/intelligent_ordering/js/{script}", source)

    def test_customer_navigation_links_to_connected_shopping_pages(self):
        header = (APP_ROOT / "templates/includes/smarto_header.html").read_text()
        footer = (APP_ROOT / "templates/includes/smarto_footer.html").read_text()
        home = (WWW / "index.html").read_text()
        for route in ("/products", "/categories", "/cart"):
            with self.subTest(route=route):
                self.assertIn(f'href="{route}"', header)
                self.assertIn(f'href="{route}"', footer)
                self.assertIn(f'href="{route}"', home)
        for page in ("payment.html", "track-order.html"):
            with self.subTest(page=page):
                self.assertIn('href="/account"', (WWW / page).read_text())

    def test_customer_pages_do_not_show_development_phase_placeholders(self):
        for path in list(WWW.glob("*.html")) + [
            APP_ROOT / "templates/includes/smarto_header.html",
            APP_ROOT / "templates/includes/smarto_footer.html",
        ]:
            with self.subTest(page=path.name):
                source = path.read_text().lower()
                self.assertNotRegex(source, r"\bphases?\b")
                self.assertNotIn("open the current catalogue", source)
                self.assertNotIn("open the existing storefront", source)

    def test_staff_pages_are_server_guarded(self):
        workflows = {
            "orders": "orders",
            "inventory": "inventory",
            "delivery": "delivery",
            "admin": "admin",
            "owner": "owner",
            "sales": "sales",
            "support": "support",
        }
        for page, controller in workflows.items():
            with self.subTest(page=page):
                self.assertTrue((WWW / f"dashboard/{controller}.py").is_file())

    def test_reporting_is_linked_from_authorized_workspaces(self):
        for page in ("sales", "owner", "inventory", "delivery"):
            with self.subTest(page=page):
                source = (WWW / f"dashboard/{page}.html").read_text()
                self.assertIn("/store#admin-dashboard", source)

    def test_login_route_remains_frappe_native(self):
        self.assertFalse((WWW / "login.html").exists())
        header = (APP_ROOT / "templates/includes/smarto_header.html").read_text()
        self.assertIn('href="/login"', header)

    def test_existing_storefront_keeps_its_delivery_login_return_path(self):
        source = (WWW / "store.html").read_text()
        self.assertIn('href="/login?redirect-to=%2Fstore%23delivery-dashboard"', source)


if __name__ == "__main__":
    unittest.main()
