import frappe
from frappe.model.document import Document


class StockWarehouse(Document):
    def validate(self):
        self.warehouse_name = (self.warehouse_name or "").strip()
        self.location = (self.location or "").strip()
        if not self.warehouse_name:
            frappe.throw("Warehouse name is required.", frappe.ValidationError)
        if self.status not in {"Active", "Inactive"}:
            frappe.throw("Select a valid warehouse status.", frappe.ValidationError)
        if self.status == "Inactive" and self.name:
            reserved = frappe.db.sql(
                """
                SELECT COALESCE(SUM(reserved_quantity), 0)
                FROM `tabStock Balance`
                WHERE warehouse = %s
                """,
                self.name,
            )[0][0]
            if reserved:
                frappe.throw(
                    "A warehouse with reserved stock cannot be deactivated.",
                    frappe.ValidationError,
                )

