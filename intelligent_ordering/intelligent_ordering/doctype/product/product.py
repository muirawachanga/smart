import frappe
from frappe.model.document import Document
from frappe.utils import flt


class Product(Document):
    def validate(self):
        self.sku = (self.sku or "").strip()
        self.product_name = (self.product_name or "").strip()
        self.currency = (self.currency or "KES").strip().upper()

        if not self.sku:
            frappe.throw("SKU is required.", frappe.ValidationError)
        if not self.product_name:
            frappe.throw("Product name is required.", frappe.ValidationError)
        if len(self.currency) != 3 or not self.currency.isalpha():
            frappe.throw(
                "Currency must be a three-letter currency code.",
                frappe.ValidationError,
            )
        if flt(self.price) < 0:
            frappe.throw("Price cannot be negative.", frappe.ValidationError)

        if self.category and not frappe.db.exists(
            "Product Category", {"name": self.category, "enabled": 1}
        ):
            frappe.throw(
                "Select an enabled product category.",
                frappe.ValidationError,
            )

    def on_trash(self):
        if frappe.db.exists("Sales Order Item", {"product": self.name}):
            frappe.throw(
                "Products referenced by order history cannot be deleted. Disable the product instead.",
                frappe.ValidationError,
            )
        if frappe.db.exists("Stock Ledger Entry", {"product": self.name}):
            frappe.throw(
                "Products referenced by stock history cannot be deleted. Disable the product instead.",
                frappe.ValidationError,
            )
