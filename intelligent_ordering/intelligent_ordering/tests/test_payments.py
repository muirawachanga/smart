import json
from unittest.mock import Mock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from intelligent_ordering.api.payments import _reconcile, _save, reconcile_payment


class TestPaymentTransaction(FrappeTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        suffix = frappe.generate_hash(length=8)
        self.user = frappe.get_doc({
            "doctype": "User", "email": f"payment-{suffix}@example.test",
            "first_name": "Payment Test", "send_welcome_email": 0,
            "user_type": "Website User", "roles": [{"role": "Customer"}],
        }).insert(ignore_permissions=True)
        profile = frappe.get_doc({
            "doctype": "Customer Profile", "user": self.user.name,
            "full_name": "Payment Test", "phone": "+254712345678", "enabled": 1,
        }).insert(ignore_permissions=True)
        area = frappe.get_doc({
            "doctype": "Delivery Area", "area_name": f"Payment Area {suffix}",
            "currency": "KES", "delivery_fee": 0, "enabled": 1,
        }).insert(ignore_permissions=True)
        address = frappe.get_doc({
            "doctype": "Customer Address", "customer": profile.name,
            "address_line_1": "1 Test Road", "city": "Nairobi",
        }).insert(ignore_permissions=True)
        product = frappe.get_doc({
            "doctype": "Product", "sku": f"PAY-{suffix}",
            "product_name": "Payment Test", "price": 250,
            "currency": "KES", "enabled": 1,
        }).insert(ignore_permissions=True)
        previous = getattr(frappe.flags, "creating_checkout_order", False)
        frappe.flags.creating_checkout_order = True
        try:
            self.order = frappe.get_doc({
                "doctype": "Sales Order", "customer": profile.name,
                "customer_name_snapshot": "Payment Test",
                "customer_phone_snapshot": "+254712345678",
                "delivery_address": address.name, "delivery_address_snapshot": "1 Test Road, Nairobi",
                "delivery_area": area.name,
                "items": [{"product": product.name, "quantity": 1}],
            }).insert(ignore_permissions=True)
        finally:
            frappe.flags.creating_checkout_order = previous
        self.payment = frappe.get_doc({
            "doctype": "Payment Transaction", "order": self.order.name,
            "customer": profile.name, "phone_number": "254712345678", "amount": 250,
            "environment": "Sandbox", "status": "Pending",
            "merchant_request_id": f"merchant-{suffix}",
            "checkout_request_id": f"checkout-{suffix}",
        })
        self.receipt = f"TEST{suffix.upper()}123"
        self.payment.callback_response = json.dumps({"Body": {"stkCallback": {
            "MerchantRequestID": self.payment.merchant_request_id,
            "CheckoutRequestID": self.payment.checkout_request_id,
            "ResultCode": 0, "ResultDesc": "Success", "CallbackMetadata": {"Item": [
                {"Name": "Amount", "Value": 250},
                {"Name": "PhoneNumber", "Value": 254712345678},
                {"Name": "MpesaReceiptNumber", "Value": self.receipt},
                {"Name": "TransactionDate", "Value": 20261113083000},
            ]},
        }}})
        _save(self.payment)

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def test_verified_payment_persists_without_confirming_order_or_moving_stock(self):
        client = Mock()
        client.query.return_value = {
            "ResponseCode": "0", "ResultCode": "0",
            "MerchantRequestID": self.payment.merchant_request_id,
            "CheckoutRequestID": self.payment.checkout_request_id,
        }
        with patch("intelligent_ordering.api.payments._client", return_value=client):
            _reconcile(self.payment)
            _reconcile(self.payment)
        self.order.reload()
        self.payment.reload()
        self.assertEqual(self.order.payment_status, "Paid")
        self.assertEqual(self.order.status, "Pending")
        self.assertEqual(self.payment.status, "Successful")
        self.assertEqual(self.payment.mpesa_receipt_number, self.receipt)
        self.assertFalse(frappe.db.exists(
            "Stock Ledger Entry", {"reference_order": self.order.name}
        ))
        client.query.assert_called_once()

    def test_payment_records_cannot_be_manually_modified_or_deleted(self):
        self.payment.status = "Successful"
        with self.assertRaises(frappe.PermissionError):
            self.payment.save(ignore_permissions=True)
        with self.assertRaises(frappe.PermissionError):
            frappe.delete_doc("Payment Transaction", self.payment.name, ignore_permissions=True)

    def test_customer_cannot_reconcile_or_read_generic_payment_documents(self):
        frappe.set_user(self.user.name)
        with self.assertRaises(frappe.PermissionError):
            reconcile_payment(self.payment.name)
        with self.assertRaises(frappe.PermissionError):
            self.payment.check_permission("read")

    def test_unpaid_order_cannot_be_completed(self):
        # Set the precondition without producing dispatches in this isolated test.
        self.order.db_set("status", "Ready for Delivery")
        self.order.reload()
        self.order.status = "Completed"
        with self.assertRaises(frappe.ValidationError):
            self.order.save(ignore_permissions=True)
