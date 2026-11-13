import re

import frappe
from frappe.model.document import Document

from intelligent_ordering.utils.delivery import validate_delivery_fee, validate_delivery_text


class DeliveryArea(Document):
    def validate(self):
        try:
            self.area_name = validate_delivery_text(self.area_name, "Area name", 140, True)
            self.delivery_fee = validate_delivery_fee(self.delivery_fee)
        except ValueError as error:
            frappe.throw(str(error), frappe.ValidationError)
        if not isinstance(self.currency, str) or not re.fullmatch(r"[A-Z]{3}", self.currency):
            frappe.throw("Currency must be a three-letter uppercase code.", frappe.ValidationError)

    def before_rename(self, *args):
        frappe.throw("Disable an old delivery area and create a new one instead.", frappe.ValidationError)
