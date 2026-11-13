import frappe
from frappe.model.document import Document


class CustomerProfile(Document):
    def validate(self):
        if self.user and frappe.db.exists(
            "Customer Profile", {"user": self.user, "name": ["!=", self.name]}
        ):
            frappe.throw("A customer profile already exists for this user.")
