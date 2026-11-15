from intelligent_ordering.utils.customer_pages import require_customer_page
from intelligent_ordering.utils.auth_pages import guard_website


@guard_website
def get_context(context):
    require_customer_page(context)
