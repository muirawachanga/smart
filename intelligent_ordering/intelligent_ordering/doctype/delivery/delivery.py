import frappe
from frappe.model.document import Document


class Delivery(Document):
    def validate(self):
        if not getattr(frappe.flags, "processing_delivery", False):
            frappe.throw("Use the authorized delivery workflow to change deliveries.", frappe.PermissionError)

    def on_trash(self):
        frappe.throw("Delivery history cannot be deleted.", frappe.PermissionError)

    def before_rename(self, *args):
        frappe.throw("Delivery history cannot be renamed.", frappe.PermissionError)
