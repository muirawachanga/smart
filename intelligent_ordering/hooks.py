app_name = "intelligent_ordering"
app_title = "SmartO"
app_publisher = "Project Team"
app_description = "SmartO ordering, inventory, and fulfillment management"
app_email = "noreply@example.com"
app_license = "MIT"

web_include_css = [
    "/assets/intelligent_ordering/css/design-tokens.css",
    "/assets/intelligent_ordering/css/site.css",
]
app_include_css = [
    "/assets/intelligent_ordering/css/design-tokens.css",
    "/assets/intelligent_ordering/css/app.css",
]

website_route_rules = [
    {"from_route": "/products/<product_id>", "to_route": "product-details"},
    {"from_route": "/order-confirmation/<order_id>", "to_route": "order-confirmation"},
]

after_install = "intelligent_ordering.install.after_install"
after_migrate = "intelligent_ordering.install.after_migrate"

override_whitelisted_methods = {
    "frappe.core.doctype.user.user.sign_up": "intelligent_ordering.api.customers.sign_up",
}
role_home_page = {
    "Customer": "/",
    "Store Manager": "/dashboard/owner",
    "Order Manager": "/dashboard/orders",
    "Inventory Manager": "/dashboard/inventory",
    "Delivery Manager": "/dashboard/delivery",
    "Delivery Staff": "/dashboard/rider",
    "Customer Support": "/dashboard/support",
}
update_website_context = "intelligent_ordering.utils.business.update_website_context"
after_request = ["intelligent_ordering.utils.website_errors.customer_error_response"]

doc_events = {
    "Website Settings": {
        "validate": "intelligent_ordering.utils.business.validate_business_settings",
        "on_update": "intelligent_ordering.utils.business.audit_business_settings",
    },
    "Sales Order": {
        "on_update": [
            "intelligent_ordering.utils.inventory.handle_order_status_change",
            "intelligent_ordering.api.deliveries.broadcast_ready_order",
            "intelligent_ordering.utils.fulfillment_notifications.handle_order_status_change",
            "intelligent_ordering.utils.audit.audit_order_status",
            "intelligent_ordering.utils.customer_notifications.on_update",
        ],
    },
    "Product": {"after_insert": "intelligent_ordering.utils.audit.audit_product",
                "on_update": "intelligent_ordering.utils.audit.audit_product"},
    "Product Category": {"after_insert": "intelligent_ordering.utils.audit.audit_category",
                         "on_update": "intelligent_ordering.utils.audit.audit_category"},
    "Payment Transaction": {"on_update": [
        "intelligent_ordering.utils.audit.audit_payment_status",
        "intelligent_ordering.utils.customer_notifications.on_update",
        "intelligent_ordering.utils.fulfillment_notifications.handle_payment_status_change",
    ]},
    "Stock Ledger Entry": {"after_insert": "intelligent_ordering.utils.audit.audit_stock_movement"},
    "Delivery": {"after_insert": "intelligent_ordering.utils.audit.audit_delivery",
                 "on_update": ["intelligent_ordering.utils.audit.audit_delivery",
                               "intelligent_ordering.utils.customer_notifications.on_update"]},
    "User": {
        "after_insert": "intelligent_ordering.utils.audit.audit_user_roles",
        "on_update": "intelligent_ordering.utils.audit.audit_user_roles",
    },
}

scheduler_events = {
    "all": [
        "intelligent_ordering.utils.fulfillment_notifications.send_pending_sms",
        "intelligent_ordering.api.deliveries.escalate_expired_broadcasts",
        "intelligent_ordering.utils.order_fulfillment.advance_confirmed_orders",
    ],
}

permission_query_conditions = {
    "Product": "intelligent_ordering.permissions.product_query",
    "Product Category": "intelligent_ordering.permissions.product_category_query",
    "Customer Profile": "intelligent_ordering.permissions.customer_profile_query",
    "Customer Address": "intelligent_ordering.permissions.customer_address_query",
    "Sales Order": "intelligent_ordering.permissions.sales_order_query",
    "Shopping Cart": "intelligent_ordering.permissions.shopping_cart_query",
    "Delivery": "intelligent_ordering.permissions.delivery_query",
}

has_permission = {
    "Customer Profile": "intelligent_ordering.permissions.customer_profile_has_permission",
    "Customer Address": "intelligent_ordering.permissions.customer_address_has_permission",
    "Sales Order": "intelligent_ordering.permissions.sales_order_has_permission",
    "Shopping Cart": "intelligent_ordering.permissions.shopping_cart_has_permission",
    "Delivery": "intelligent_ordering.permissions.delivery_has_permission",
}
