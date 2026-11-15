from intelligent_ordering.api.policies import current_policy

no_cache = 1


def get_context(context):
    context.policy_title = "Terms and Conditions"
    context.policy = current_policy("terms")
