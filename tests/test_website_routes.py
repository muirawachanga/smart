import unittest
from pathlib import Path

from intelligent_ordering.hooks import (
    app_include_css,
    website_route_rules,
    web_include_css,
)


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
    def test_role_pages_and_auth_include_script_startup_warning(self):
        routes = [
            "dashboard/admin.html", "dashboard/owner.html", "dashboard/sales.html",
            "dashboard/orders.html", "dashboard/inventory.html", "dashboard/delivery.html",
            "dashboard/support.html", "account.html", "account/profile.html",
            "account/addresses.html", "account/payments.html", "account/notifications.html",
            "store.html",
        ]
        for route in routes:
            with self.subTest(route=route):
                self.assertIn("page_script_warning.html", (WWW / route).read_text())
        self.assertIn("page_script_warning.html", (APP_ROOT / "templates/auth.html").read_text())
        warning = (APP_ROOT / "templates/includes/page_script_warning.html").read_text()
        self.assertIn('role="alert"', warning)
        self.assertNotIn(" hidden", warning)

    def test_smart_design_assets_are_registered_and_logo_is_shared(self):
        logo_path = "/assets/intelligent_ordering/images/smarto-logo.svg"
        self.assertIn("/assets/intelligent_ordering/css/design-tokens.css", web_include_css)
        self.assertIn("/assets/intelligent_ordering/css/site.css", web_include_css)
        self.assertIn("/assets/intelligent_ordering/css/design-tokens.css", app_include_css)
        self.assertIn("/assets/intelligent_ordering/css/app.css", app_include_css)
        self.assertTrue((APP_ROOT / "public/images/smarto-logo.svg").is_file())
        self.assertIn(logo_path, (APP_ROOT / "templates/includes/smarto_logo.html").read_text())
        for name in ("smarto_header", "smarto_footer"):
            self.assertIn("smarto_logo.html", (APP_ROOT / f"templates/includes/{name}.html").read_text())

    def test_static_pages_use_the_shared_smarto_layout(self):
        for route, template in SHELL_ROUTES.items():
            with self.subTest(route=route):
                source = (WWW / template).read_text()
                if route in {"/register", "/forgot-password", "/reset-password"}:
                    source += (APP_ROOT / "templates/auth.html").read_text()
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
            "track-order.html": "order-pages.js",
            "dashboard/owner.html": "role-dashboard.js",
            "dashboard/sales.html": "role-dashboard.js",
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

    def test_checkout_and_payment_navigation_avoids_the_combined_storefront(self):
        for page in ("checkout.html", "order-confirmation.html", "payment.html"):
            with self.subTest(page=page):
                source = (WWW / page).read_text()
                self.assertIn('href="/account">Order history</a>', source)
                self.assertRegex(source, r'href="/checkout"[^>]*>Checkout</a>')
                self.assertNotIn("/store", source)

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

    def test_admin_dashboard_uses_real_data_and_preserves_native_management_routes(self):
        source = (WWW / "dashboard/admin.html").read_text()
        script = (APP_ROOT / "public/js/admin-dashboard.js").read_text()
        controller = (WWW / "dashboard/admin.py").read_text()
        self.assertIn("/assets/intelligent_ordering/js/admin-dashboard.js", source)
        self.assertIn('href="/app/product"', source)
        self.assertIn('href="/app/product-category"', source)
        self.assertIn('href="/app/user"', source)
        for endpoint in (
            "administration.dashboard", "administration.sales_analytics",
            "orders.list_orders", "payments.list_transactions", "inventory.list_stock",
        ):
            with self.subTest(endpoint=endpoint):
                self.assertIn(endpoint, script)
        self.assertIn('require_staff_page(context, "admin")', controller)

    def test_owner_and_sales_dashboards_use_live_role_scoped_analytics(self):
        source = (APP_ROOT / "public/js/role-dashboard.js").read_text()
        for role, controller, heading in (
            ("owner", "owner", "Business overview."),
            ("sales", "sales", "Sales performance."),
        ):
            with self.subTest(role=role):
                page = (WWW / f"dashboard/{role}.html").read_text()
                self.assertIn(f'data-role-dashboard="{role}"', page)
                self.assertIn(heading, page)
                self.assertIn("role-dashboard.js", page)
                self.assertIn(f'require_staff_page(context, "{controller}")',
                              (WWW / f"dashboard/{controller}.py").read_text())
        self.assertIn("administration.dashboard", source)
        self.assertIn("administration.sales_analytics", source)
        self.assertIn("Successful payments", source)

    def test_management_workspace_uses_role_filtered_navigation_and_shared_styles(self):
        source = (WWW / "store.html").read_text()
        script = (APP_ROOT / "public/js/administration.js").read_text()
        payments = (APP_ROOT / "public/js/payments.js").read_text()
        self.assertIn('/assets/intelligent_ordering/css/app.css', source)
        self.assertIn('id="admin-section-navigation"', source)
        self.assertIn('data-admin-access="finance"', source)
        self.assertIn('data-admin-access="inventory"', source)
        self.assertIn('data-admin-access="delivery"', source)
        self.assertIn('link.hidden = !groups.some((group) => access[group])', script)
        self.assertIn("Technical transaction data", payments)
        self.assertIn('get("payments.payment_summary")', payments)

    def test_responsive_styles_include_reduced_motion_and_mobile_management_layouts(self):
        tokens = (APP_ROOT / "public/css/design-tokens.css").read_text()
        site_styles = (APP_ROOT / "public/css/site.css").read_text()
        app_styles = (APP_ROOT / "public/css/app.css").read_text()
        self.assertIn(":focus-visible", tokens)
        self.assertIn("@media (prefers-reduced-motion: reduce)", tokens)
        self.assertIn("@media (max-width: 42rem)", site_styles)
        self.assertIn("@media (max-width: 40rem)", app_styles)
        self.assertIn('.ordering-shell[data-store-view="admin"]', app_styles)
        self.assertIn("overflow-x: auto", app_styles)

    def test_customer_order_tracking_uses_owner_scoped_order_page(self):
        source = (WWW / "track-order.html").read_text()
        self.assertIn('data-orders-page="customer"', source)
        self.assertIn('href="/login?redirect-to=%2Ftrack-order"', source)
        self.assertIn('id="order-detail"', source)

    def test_authentication_pages_share_branded_forms_instead_of_native_login(self):
        self.assertTrue((WWW / "login.html").exists())
        for page in ("login", "register", "forgot-password", "reset-password"):
            self.assertIn('extends "templates/auth.html"', (WWW / f"{page}.html").read_text())
        self.assertIn("authentication.js", (APP_ROOT / "templates/auth.html").read_text())
        self.assertIn("www/reset-password.html", (WWW / "update-password.html").read_text())
        header = (APP_ROOT / "templates/includes/smarto_header.html").read_text()
        self.assertIn('href="/login"', header)

    def test_existing_storefront_keeps_its_delivery_login_return_path(self):
        source = (WWW / "store.html").read_text()
        self.assertIn('href="/login?redirect-to=%2Fstore%23delivery-dashboard"', source)


if __name__ == "__main__":
    unittest.main()
