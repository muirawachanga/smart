import frappe

from intelligent_ordering.utils.policy_content import POLICY_CONTENT, POLICY_DRAFT_VERSION, REVIEW_INSTRUCTIONS


POLICIES = {
    "terms": "Terms and Conditions",
    "privacy": "Privacy Policy",
    "refund": "Refund Policy",
    "delivery": "Delivery Policy",
}


def current_policy(kind):
    rows = frappe.get_all(
        "SmartO Policy Version",
        filters={"policy_type": POLICIES[kind], "status": "Published"},
        fields=["name", "title", "version", "content", "published_at"],
        order_by="published_at desc, creation desc, name desc", limit_page_length=1,
    )
    return rows[0] if rows else None


@frappe.whitelist(allow_guest=True)
def registration_policies():
    terms, privacy = current_policy("terms"), current_policy("privacy")
    return {
        "available": bool(terms and privacy),
        "terms": {"name": terms.name, "version": terms.version} if terms else None,
        "privacy": {"name": privacy.name, "version": privacy.version} if privacy else None,
    }


def require_acceptance(terms_version, privacy_version, accept_terms, acknowledge_privacy):
    if accept_terms not in (1, "1") or acknowledge_privacy not in (1, "1"):
        frappe.throw("Accept the Terms and acknowledge the Privacy Policy to register.", frappe.ValidationError)
    policies = registration_policies()
    if not policies["available"]:
        frappe.throw("Registration is unavailable until Terms and Privacy policies are published.",
                     frappe.ValidationError)
    # Reject stale acceptance when newer versions were published after the page loaded.
    if terms_version != policies["terms"]["name"] or privacy_version != policies["privacy"]["name"]:
        frappe.throw("Policies have changed. Reload registration and review the current versions.",
                     frappe.ValidationError)


def ensure_policy_drafts():
    for kind in POLICIES.values():
        if frappe.db.exists("SmartO Policy Version", {"policy_type": kind, "version": POLICY_DRAFT_VERSION}):
            continue
        frappe.get_doc({
            "doctype": "SmartO Policy Version", "policy_type": kind,
            "title": kind, "version": POLICY_DRAFT_VERSION, "status": "Draft",
            "content": REVIEW_INSTRUCTIONS + POLICY_CONTENT[kind],
        }).insert(ignore_permissions=True)
