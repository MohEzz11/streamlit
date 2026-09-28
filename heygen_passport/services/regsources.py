"""Regulatory / procedure references that checklist items trace back to."""

from .. import audit
from ..db import row, rows, transaction, utcnow
from ..permissions import require
from ..security import ValidationError, clean_text
from .common import parse_date, today_local


def list_sources(conn, actor, include_inactive=False):
    require(actor, "regsource.view")
    out = rows(conn, """SELECT r.*, (SELECT COUNT(*) FROM hp_template_items i WHERE i.reg_source_id=r.id
                        AND i.active=1) AS linked_items FROM hp_reg_sources r"""
               + ("" if include_inactive else " WHERE r.active=1") + " ORDER BY r.authority, r.title")
    today = today_local(conn).isoformat()
    for r in out:
        r["review_overdue"] = bool(r["review_date"] and r["review_date"] < today)
    return out


def save_source(conn, actor, data, source_id=None):
    require(actor, "regsource.manage")
    c = {
        "title": clean_text(data.get("title"), "Title", 200, required=True),
        "authority": clean_text(data.get("authority"), "Authority / owner", 120, required=True),
        "document_ref": clean_text(data.get("document_ref"), "Document reference", 120),
        "version": clean_text(data.get("version"), "Version", 60),
        "url": clean_text(data.get("url"), "URL", 500),
        "review_date": parse_date(data.get("review_date"), "Next review date"),
        "notes": clean_text(data.get("notes"), "Notes", 2000),
        "active": int(data.get("active", True)),
    }
    if c["url"] and not c["url"].startswith(("https://", "http://")):
        raise ValidationError("URL must start with https://")
    keys = list(c)
    with transaction(conn):
        if source_id:
            old = row(conn, "SELECT * FROM hp_reg_sources WHERE id=?", (source_id,))
            if not old:
                raise ValidationError("Reference not found.")
            conn.execute(f"UPDATE hp_reg_sources SET {', '.join(k + '=?' for k in keys)}, updated_at=?, updated_by=? "
                         "WHERE id=?", [c[k] for k in keys] + [utcnow(), actor.user_id, source_id])
            audit.log(conn, actor, "reg_source.update", "reg_source", source_id,
                      **{k: {"old": old[k], "new": c[k]} for k in keys if old[k] != c[k]})
        else:
            cur = conn.execute(f"INSERT INTO hp_reg_sources({', '.join(keys)}, created_at, created_by) "
                               f"VALUES ({', '.join('?' for _ in keys)}, ?, ?)",
                               [c[k] for k in keys] + [utcnow(), getattr(actor, "user_id", None)])
            source_id = cur.lastrowid
            audit.log(conn, actor, "reg_source.create", "reg_source", source_id, title=c["title"])
    return source_id
