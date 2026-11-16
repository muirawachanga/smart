import frappe
from frappe.model.document import Document


class DeliveryRiderLocation(Document):
    def validate(self):
        if not getattr(frappe.flags, "sharing_delivery_location", False):
            frappe.throw("Rider locations are managed by the rider location workflow.", frappe.PermissionError)

    def on_trash(self):
        frappe.throw("Use the rider location workflow to clear a location.", frappe.PermissionError)

    def before_rename(self, *args):
        frappe.throw("Rider locations cannot be renamed.", frappe.PermissionError)
