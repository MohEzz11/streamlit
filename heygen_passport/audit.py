"""Append-only audit trail."""

import json

from .db import utcnow


def log(conn, actor, action, entity_type, entity_id=None, department_id=None, **details):
    conn.execute(
        """INSERT INTO hp_audit_log(at, user_id, username, action, entity_type, entity_id,
                                    department_id, details)
           VALUES (?,?,?,?,?,?,?,?)""",
        (utcnow(), getattr(actor, "user_id", None), getattr(actor, "username", "system"),
         action, entity_type, entity_id, department_id,
         json.dumps(details, default=str) if details else None))
