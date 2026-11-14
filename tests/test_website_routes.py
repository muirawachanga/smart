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
    "/dashboard/owner": "dashboard/owner.html",
    "/dashboard/admin": "dashboard/admin.html",
    "/dashboard/sales": "dashboard/sales.html",
    "/dashboard/orders": "dashboard/orders.html",
    "/dashboard/inventory": "dashboard/inventory.html",
    "/dashboard/delivery": "dashboard/delivery.html",
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

    def test_login_route_remains_frappe_native(self):
        self.assertFalse((WWW / "login.html").exists())
        header = (APP_ROOT / "templates/includes/smarto_header.html").read_text()
        self.assertIn('href="/login"', header)

    def test_existing_storefront_keeps_its_delivery_login_return_path(self):
        source = (WWW / "store.html").read_text()
        self.assertIn('href="/login?redirect-to=%2Fstore%23delivery-dashboard"', source)


if __name__ == "__main__":
    unittest.main()
