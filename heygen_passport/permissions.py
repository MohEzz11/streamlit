"""Role-based permissions, enforced in the service layer (backend).

The UI hides actions a user cannot perform, but every service function calls
require() itself, so a hidden button is never the only protection.
"""

from dataclasses import dataclass


class PermissionDenied(Exception):
    """Raised when the current user may not perform an action."""


ROLES = ("staff", "supervisor", "manager", "admin")
ROLE_LABELS = {"staff": "Staff member", "supervisor": "Department supervisor",
               "manager": "Heygen Manager", "admin": "Administrator"}

_STAFF = {
    "duty.view_own", "duty.complete_own", "expiry.view", "expiry.record_action",
    "feedback.view_own", "profile.view_own",
}
_SUPERVISOR = _STAFF | {
    "dept.view", "template.manage", "schedule.manage", "duty.view_dept", "duty.verify",
    "ca.view", "ca.manage", "expiry.manage_items", "staff.view", "cert.view",
    "score.view", "coaching.manage", "reports.view", "alerts.ack", "regsource.view",
}
_MANAGER = _SUPERVISOR | {
    "all_departments", "score.award", "score.configure", "expiry.configure",
    "staff.edit", "cert.manage", "access.manage", "regsource.manage",
}
_ADMIN = (_MANAGER - {"score.award"}) | {
    "admin.users", "admin.departments", "admin.settings", "admin.audit",
    "admin.profile_fields",
}

ROLE_PERMISSIONS = {"staff": _STAFF, "supervisor": _SUPERVISOR,
                    "manager": _MANAGER, "admin": _ADMIN}


@dataclass(frozen=True)
class Actor:
    user_id: int
    username: str
    role: str
    staff_id: int = None
    department_id: int = None
    can_score: bool = False

    @property
    def all_departments(self):
        return "all_departments" in ROLE_PERMISSIONS.get(self.role, set())


def has(actor, perm, department_id=None):
    if actor is None or actor.role not in ROLE_PERMISSIONS:
        return False
    perms = ROLE_PERMISSIONS[actor.role]
    allowed = perm in perms
    # Supervisors may score only when explicitly granted.
    if perm == "score.award" and actor.role == "supervisor" and actor.can_score:
        allowed = True
    if not allowed:
        return False
    if department_id is not None and not actor.all_departments:
        return actor.department_id is not None and int(department_id) == int(actor.department_id)
    return True


def require(actor, perm, department_id=None):
    if not has(actor, perm, department_id):
        raise PermissionDenied("You do not have permission to do this.")


def dept_scope(actor):
    """None means all departments; otherwise the only department visible."""
    return None if actor.all_departments else actor.department_id
