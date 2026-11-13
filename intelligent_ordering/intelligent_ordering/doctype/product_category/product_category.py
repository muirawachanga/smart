import frappe
from frappe.model.document import Document


class ProductCategory(Document):
    def validate(self):
        self.category_name = (self.category_name or "").strip()
        if not self.category_name:
            frappe.throw("Category name is required.", frappe.ValidationError)

    def on_trash(self):
        if frappe.db.exists("Product", {"category": self.name}):
            frappe.throw(
                "Categories used by products cannot be deleted. Disable the category instead.",
                frappe.ValidationError,
            )
        if frappe.db.exists("Sales Order Item", {"product_category_snapshot": self.name}):
            frappe.throw(
                "Categories referenced by order history cannot be deleted.",
                frappe.ValidationError,
            )

    def before_rename(self, *args):
        frappe.throw("Categories cannot be renamed because order-time category snapshots are retained.",
                     frappe.ValidationError)
