import re

import frappe

from intelligent_ordering.utils.audit import record_admin_event


BUSINESS_FIELDS = {
    "name": "smarto_business_name",
    "email": "smarto_contact_email",
    "phone": "smarto_contact_phone",
    "address": "smarto_business_address",
}


def ensure_business_fields():
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

    create_custom_fields({
        "Website Settings": [
            {"fieldname": "smarto_business_section", "label": "SmartO business",
             "fieldtype": "Section Break", "insert_after": "app_name"},
            {"fieldname": BUSINESS_FIELDS["name"], "label": "Public business name",
             "fieldtype": "Data", "insert_after": "smarto_business_section"},
            {"fieldname": BUSINESS_FIELDS["email"], "label": "Public support email",
             "fieldtype": "Data", "options": "Email", "insert_after": BUSINESS_FIELDS["name"]},
            {"fieldname": BUSINESS_FIELDS["phone"], "label": "Public support phone",
             "fieldtype": "Data", "insert_after": BUSINESS_FIELDS["email"]},
            {"fieldname": BUSINESS_FIELDS["address"], "label": "Public business address",
             "fieldtype": "Small Text", "insert_after": BUSINESS_FIELDS["phone"]},
        ],
    }, update=True)


def validate_profile(values):
    profile = {}
    for key, limit in (("name", 140), ("email", 140), ("phone", 30), ("address", 500)):
        value = values.get(key)
        if not isinstance(value, str) or len(value.strip()) > limit:
            raise ValueError(f"Business {key} must be text of at most {limit} characters.")
        profile[key] = value.strip()
    if not profile["name"]:
        raise ValueError("Enter the public business name.")
    if not profile["email"] and not profile["phone"]:
        raise ValueError("Enter a public support email or phone number.")
    if profile["email"] and not re.fullmatch(r"[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+", profile["email"]):
        raise ValueError("Enter a valid support email address.")
    if profile["phone"] and not re.fullmatch(r"\+?[0-9][0-9 ()-]{5,28}[0-9]", profile["phone"]):
        raise ValueError("Enter a valid support phone number.")
    if any(ord(char) < 32 and char not in "\n\r\t" for value in profile.values() for char in value):
        raise ValueError("Business details contain invalid control characters.")
    return profile


def get_business_profile():
    settings = frappe.get_cached_doc("Website Settings")
    return {key: settings.get(field) or "" for key, field in BUSINESS_FIELDS.items()}


def update_website_context(context):
    context["smarto_business"] = get_business_profile()


def validate_business_settings(doc, method=None):
    values = {key: doc.get(field) or "" for key, field in BUSINESS_FIELDS.items()}
    if not any(values.values()):
        return
    try:
        profile = validate_profile(values)
    except ValueError as error:
        frappe.throw(str(error), frappe.ValidationError)
    for key, field in BUSINESS_FIELDS.items():
        doc.set(field, profile[key])


def audit_business_settings(doc, method=None):
    original = doc.get_doc_before_save()
    changed = [
        field for field in BUSINESS_FIELDS.values()
        if doc.get(field) != (original.get(field) if original else None)
    ]
    if changed:
        record_admin_event("Business settings updated", "Website Settings", doc.name, ", ".join(changed))
