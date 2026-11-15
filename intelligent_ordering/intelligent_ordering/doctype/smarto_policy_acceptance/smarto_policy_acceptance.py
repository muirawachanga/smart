import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class SmartOPolicyAcceptance(Document):
    def validate(self):
        if not self.is_new():
            frappe.throw("Policy acceptance records cannot be changed.", frappe.ValidationError)
        self.accepted_at = now_datetime()
        for field, kind in (
            ("terms_version", "Terms and Conditions"), ("privacy_version", "Privacy Policy"),
        ):
            if not frappe.db.exists("SmartO Policy Version", {
                "name": self.get(field), "policy_type": kind, "status": "Published",
            }):
                frappe.throw("Acceptance requires published Terms and Privacy versions.", frappe.ValidationError)
        if frappe.db.get_value("Customer Profile", self.customer, "user") != self.user:
            frappe.throw("Acceptance must belong to the registered customer.", frappe.ValidationError)

    def on_trash(self):
        frappe.throw("Policy acceptance records must be retained for audit.", frappe.ValidationError)
