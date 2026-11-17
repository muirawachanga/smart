from intelligent_ordering.utils.auth_pages import guard_website
from intelligent_ordering.utils.staff_pages import require_staff_page

no_cache = 1


@guard_website
def get_context(context):
    require_staff_page(context, "delivery_areas")
