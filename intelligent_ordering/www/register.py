from intelligent_ordering.api.policies import registration_policies
from intelligent_ordering.utils.auth_pages import prepare_auth_page

no_cache = 1


def get_context(context):
    prepare_auth_page(context)
    context.registration_policies = registration_policies()
