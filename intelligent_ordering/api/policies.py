import frappe


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
    if terms_version != policies["terms"]["name"] or privacy_version != policies["privacy"]["name"]:
        frappe.throw("Policies have changed. Reload registration and review the current versions.",
                     frappe.ValidationError)


def ensure_policy_drafts():
    for kind in POLICIES.values():
        if frappe.db.exists("SmartO Policy Version", {"policy_type": kind}):
            continue
        frappe.get_doc({
            "doctype": "SmartO Policy Version", "policy_type": kind,
            "title": kind, "version": "review-draft", "status": "Draft",
            "content": (
                f"UNPUBLISHED ADMINISTRATOR REVIEW DRAFT - {kind}\n\n"
                "Replace this review brief with approved policy text before publishing.\n"
                "Confirm the applicable jurisdiction, business identity, actual contact channel, "
                "customer rights, and operational commitments. Do not invent legal approvals.\n\n"
                + {
                    "Terms and Conditions": "Review account eligibility, ordering, pricing, payment, cancellation, dispute handling, and applicable law.",
                    "Privacy Policy": "Review collected data, processing purposes, payment providers, retention, customer rights, security, and optional marketing.",
                    "Refund Policy": "Review refund eligibility, exclusions, request process, verified M-Pesa refunds, timelines, and statutory rights.",
                    "Delivery Policy": "Review delivery areas, fees, scheduling, failed deliveries, tracking, and actual delivery commitments.",
                }[kind]
            ),
        }).insert(ignore_permissions=True)
