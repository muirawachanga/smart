import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import getdate, now_datetime

from intelligent_ordering.api.administration import (
    customer_activity,
    dashboard,
    export_report,
    list_customers,
    management_activity,
    sales_analytics,
)
from intelligent_ordering.api.inventory import adjust_stock
from intelligent_ordering.api.payments import _save


class TestAdministrationAnalytics(FrappeTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        self.baseline = dashboard()
        suffix = frappe.generate_hash(length=8)
        self.customer = self._make_user(f"admin-customer-{suffix}@example.test", "Customer")
        self.profile = frappe.get_doc({
            "doctype": "Customer Profile", "user": self.customer.name,
            "full_name": "Analytics Customer", "phone": "+254712345678", "enabled": 1,
        }).insert(ignore_permissions=True)
        self.category = frappe.get_doc({
            "doctype": "Product Category", "category_name": f"Analytics {suffix}",
            "enabled": 1,
        }).insert(ignore_permissions=True)
        self.product = frappe.get_doc({
            "doctype": "Product", "sku": f"ANALYTICS-{suffix}",
            "product_name": "Analytics Product", "category": self.category.name,
            "price": 100, "currency": "KES", "enabled": 1,
        }).insert(ignore_permissions=True)
        self.area = frappe.get_doc({
            "doctype": "Delivery Area", "area_name": f"Analytics Area {suffix}",
            "currency": "KES", "delivery_fee": 0, "enabled": 1,
        }).insert(ignore_permissions=True)
        address = frappe.get_doc({
            "doctype": "Customer Address", "customer": self.profile.name,
            "address_line_1": "1 Analytics Road", "city": "Nairobi",
        }).insert(ignore_permissions=True)
        previous = getattr(frappe.flags, "creating_checkout_order", False)
        frappe.flags.creating_checkout_order = True
        try:
            self.order = frappe.get_doc({
                "doctype": "Sales Order", "customer": self.profile.name,
                "customer_name_snapshot": "Analytics Customer",
                "customer_phone_snapshot": "+254712345678",
                "delivery_address": address.name,
                "delivery_address_snapshot": "1 Analytics Road, Nairobi",
                "delivery_area": self.area.name,
                "items": [{"product": self.product.name, "quantity": 2}],
            }).insert(ignore_permissions=True)
        finally:
            frappe.flags.creating_checkout_order = previous
        self.transaction_date = now_datetime()
        self.payment = frappe.get_doc({
            "doctype": "Payment Transaction", "order": self.order.name,
            "customer": self.profile.name, "phone_number": "254712345678",
            "amount": 200, "environment": "Sandbox", "status": "Successful",
            "merchant_request_id": f"merchant-{suffix}",
            "checkout_request_id": f"checkout-{suffix}",
            "mpesa_receipt_number": f"ANALYTICS{suffix.upper()}",
            "transaction_date": self.transaction_date,
        })
        _save(self.payment)
        self.warehouse = frappe.get_doc({
            "doctype": "Stock Warehouse", "warehouse_name": f"Analytics WH {suffix}",
            "status": "Active",
        }).insert(ignore_permissions=True)
        adjust_stock(self.product.name, self.warehouse.name, "Opening", 4)
        previous = getattr(frappe.flags, "processing_delivery", False)
        frappe.flags.processing_delivery = True
        try:
            frappe.get_doc({
                "doctype": "Delivery", "order": self.order.name,
                "customer": self.profile.name, "customer_name": "Analytics Customer",
                "customer_phone": "+254712345678",
                "delivery_address": "1 Analytics Road, Nairobi",
                "delivery_area": self.area.name, "currency": "KES",
                "delivery_fee": 0, "status": "Assigned",
            }).insert(ignore_permissions=True)
        finally:
            frappe.flags.processing_delivery = previous

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def test_dashboard_counts_real_order_payment_stock_and_delivery_records(self):
        result = dashboard()
        self.assertEqual(result["business"]["total_orders"], self.baseline["business"]["total_orders"] + 1)
        self.assertEqual(result["business"]["total_customers"], self.baseline["business"]["total_customers"] + 1)
        self.assertEqual(result["business"]["total_products"], self.baseline["business"]["total_products"] + 1)
        self.assertEqual(result["business"]["successful_payments"], self.baseline["business"]["successful_payments"] + 1)
        self.assertAlmostEqual(result["business"]["total_sales"], self.baseline["business"]["total_sales"] + 200)
        self.assertGreaterEqual(result["inventory"]["available_stock"], 4)
        self.assertGreaterEqual(result["delivery"]["assigned_deliveries"], 1)

    def test_sales_series_and_product_category_area_filters_use_paid_records(self):
        date = getdate(self.transaction_date).isoformat()
        result = sales_analytics(
            start_date=date, end_date=date, product=self.product.name,
            category=self.category.name, order_status="Pending",
            payment_status="Successful",
        )
        self.assertEqual(sum(float(row.sales) for row in result["daily"]), 200)
        self.assertEqual(sum(float(row.item_sales) for row in result["by_product"]), 200)
        self.assertEqual(sum(float(row.item_sales) for row in result["by_category"]), 200)
        self.assertEqual(sum(float(row.sales) for row in result["by_delivery_area"]), 200)
        self.assertEqual(result["filters"]["start_date"], date)

    def test_date_range_excludes_payments_outside_selected_window(self):
        result = sales_analytics(start_date="2000-01-01", end_date="2000-01-02")
        self.assertFalse(any(row.period >= "2000-01" for row in result["daily"]))

    def test_csv_and_excel_reports_contain_real_database_rows(self):
        export_report("sales", "csv")
        csv_response = frappe.response
        self.assertEqual(csv_response["filename"], "sales-report.csv")
        self.assertIn(self.payment.name, csv_response["filecontent"])
        self.assertIn(self.payment.mpesa_receipt_number, csv_response["filecontent"])
        export_report("inventory", "xlsx")
        excel_response = frappe.response
        self.assertEqual(excel_response["filename"], "inventory-report.xlsx")
        self.assertEqual(
            excel_response["content_type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertTrue(excel_response["filecontent"])

    def test_customer_role_cannot_view_administration_or_export_reports(self):
        frappe.set_user(self.customer.name)
        with self.assertRaises(frappe.PermissionError):
            dashboard()
        with self.assertRaises(frappe.PermissionError):
            sales_analytics()
        with self.assertRaises(frappe.PermissionError):
            export_report("payments", "csv")

    def test_support_customer_search_excludes_payment_aggregates_and_keeps_history_read_only(self):
        support = self._make_user(f"support-{frappe.generate_hash(length=8)}@example.test", "Customer Support")
        frappe.set_user(support.name)
        result = list_customers(search=self.profile.name)
        self.assertEqual(result["customers"][0]["name"], self.profile.name)
        self.assertNotIn("successful_payments", result["customers"][0])
        history = customer_activity(self.profile.name)
        self.assertEqual(history["orders"][0]["name"], self.order.name)
        with self.assertRaises(frappe.PermissionError):
            management_activity()
        with self.assertRaises(frappe.PermissionError):
            export_report("payments", "csv")

    def _make_user(self, email, role):
        user = frappe.get_doc({
            "doctype": "User", "email": email,
            "first_name": email.split("@", 1)[0], "send_welcome_email": 0,
            "user_type": "Website User", "roles": [{"role": role}],
        }).insert(ignore_permissions=True)
        return user
