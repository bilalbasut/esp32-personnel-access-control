"""Small helper so every view that mutates something calls one function the
same way, instead of each view constructing AuditLog rows by hand."""
from accounts.models import AuditLog


def log_action(request, action, target_repr="", details=None):
    """Records a who-did-what entry for the current request.

    `operator` is None (recorded/shown as "system") when the request isn't
    authenticated - which, as of this rollout, is every request until the
    frontend starts sending a token. That's expected, not a bug: audit
    coverage improves automatically as soon as operators start logging in,
    with no further backend changes needed.
    """
    user = getattr(request, "user", None)
    operator = user if user is not None and getattr(user, "is_authenticated", False) else None
    AuditLog.objects.create(
        operator=operator,
        action=action,
        target_repr=target_repr,
        details=details or {},
    )
