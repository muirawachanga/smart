from intelligent_ordering.api.policies import current_policy

no_cache = 1


def get_context(context):
    context.policy_title = "Delivery Policy"
    context.policy = current_policy("delivery")
