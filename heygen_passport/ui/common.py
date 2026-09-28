"""Shared UI helpers: DB connection, session, status badges and a save
wrapper that always tells the user whether something was recorded."""

import datetime as dt
import html

import pandas as pd
import streamlit as st

from .. import db
from ..permissions import PermissionDenied, has
from ..security import ValidationError
from ..services import common as svc

STATUS_BADGE = {
    # value: (label, colour)
    "not_started": ("Not started", "gray"), "in_progress": ("In progress", "blue"),
    "completed": ("Completed", "green"), "overdue": ("Overdue", "red"),
    "exception": ("Exception raised", "orange"),
    "ok": ("OK", "green"), "expiring_soon": ("Expiring soon", "orange"), "expired": ("Expired", "red"),
    "removed": ("Removed", "gray"), "disposed": ("Disposed", "gray"), "action_required": ("Action required", "red"),
    "no_expiry": ("No expiry", "gray"),
    "open": ("Open", "red"), "resolved": ("Resolved", "green"), "cancelled": ("Cancelled", "gray"),
    "pending": ("Awaiting verification", "violet"), "verified": ("Verified", "green"), "rejected": ("Rejected - redo", "red"),
    "green": ("Green - meeting target", "green"), "amber": ("Amber - needs attention", "orange"),
    "red": ("Red - below target / urgent", "red"), "none": ("No data", "gray"),
    "critical": ("Critical risk", "red"), "high": ("High", "orange"), "medium": ("Medium", "blue"), "low": ("Low", "gray"),
}
ICON = {"green": "🟢", "amber": "🟠", "red": "🔴", "none": "⚪"}

CSS = """
<style>
  .block-container {padding-top: 1.2rem; max-width: 1200px;}
  .stButton>button, .stFormSubmitButton>button {min-height: 2.8rem; font-weight: 600;}
  .hp-note {background: var(--hp-note-bg, #f3f6fb); border-left: 4px solid #2b5c9e; padding: .6rem .8rem;
            border-radius: 4px; font-size: .9rem; color: inherit;}
  @media (prefers-color-scheme: dark) { .hp-note { --hp-note-bg: #1c2533; } }
  .hp-meta {color: #5a6472; font-size: .85rem;}
  @media (max-width: 640px) { .block-container {padding-left: 1rem; padding-right: 1rem;} }
</style>
"""


def conn():
    if "hp_conn" not in st.session_state:
        c = db.connect()
        db.migrate_up(c)
        st.session_state["hp_conn"] = c
    return st.session_state["hp_conn"]


def actor():
    return st.session_state.get("hp_actor")


def badge(key, label=None):
    text, color = STATUS_BADGE.get(key, (key, "gray"))
    st.badge(label or text, color=color)


def status_text(key):
    return STATUS_BADGE.get(key, (key, ""))[0]


def esc(v):
    return html.escape(str(v or ""))


def note(text):
    st.markdown(f'<div class="hp-note">{esc(text)}</div>', unsafe_allow_html=True)


def fmt(iso, with_date=True):
    return svc.fmt_local(conn(), iso, with_date)


def flash_show():
    msg = st.session_state.pop("hp_flash", None)
    if msg:
        kind, text = msg
        (st.success if kind == "ok" else st.error)(text)
        st.toast(text)


def save(fn, *args, success="Saved.", rerun=True, **kwargs):
    """Run a service call and report clearly whether it was recorded."""
    try:
        result = fn(*args, **kwargs)
    except (ValidationError, PermissionDenied) as e:
        st.error(f"NOT saved: {e}")
        return None
    except db.OperationalError as e:
        st.error(f"NOT saved: the database is busy or unavailable ({e}). Your entry is still on screen - "
                 "please try again.")
        return None
    except db.IntegrityError as e:
        st.error(f"NOT saved: the data conflicts with an existing record ({e}).")
        return None
    except Exception as e:  # noqa: BLE001 - never hide a failed save
        st.error(f"NOT saved: unexpected error ({type(e).__name__}). Please try again or tell a supervisor.")
        return None
    stamp = svc.now_local(conn()).strftime("%H:%M:%S")
    st.session_state["hp_flash"] = ("ok", f"✅ {success} Recorded at {stamp} (hotel time).")
    if rerun:
        st.rerun()
    return result


def guard(fn, *args, **kwargs):
    """Run a read call, showing a friendly message on permission errors."""
    try:
        return fn(*args, **kwargs)
    except PermissionDenied as e:
        st.error(str(e))
        st.stop()
    except ValidationError as e:
        st.error(str(e))
        st.stop()


def date_range_picker(key, default_days=30):
    today = svc.today_local(conn())
    c1, c2 = st.columns(2)
    d1 = c1.date_input("From", today - dt.timedelta(days=default_days - 1), key=f"{key}_from")
    d2 = c2.date_input("To", today, key=f"{key}_to")
    if d1 > d2:
        st.warning("'From' is after 'To'; dates swapped.")
        d1, d2 = d2, d1
    return d1, d2


def dept_filter(key, label="Department", allow_all=True):
    a = actor()
    depts = svc.visible_departments(conn(), a)
    if not a.all_departments:
        return a.department_id
    opts = ([None] if allow_all else []) + [d["id"] for d in depts]
    names = {d["id"]: d["name"] for d in depts}
    return st.selectbox(label, opts, format_func=lambda i: "All departments" if i is None else names[i], key=key)


def df(records, columns=None, rename=None):
    frame = pd.DataFrame(records)
    if frame.empty:
        return frame
    if columns:
        frame = frame[[c for c in columns if c in frame.columns]]
    if rename:
        frame = frame.rename(columns=rename)
    return frame


def csv_button(frame, filename, label="Export CSV"):
    if frame is not None and not frame.empty:
        st.download_button(label, frame.to_csv(index=False).encode("utf-8"), file_name=filename,
                           mime="text/csv", key=f"dl_{filename}")


def upload_tuple(uploaded):
    if uploaded is None:
        return None
    return (uploaded.name, uploaded.getvalue())


def show_evidence(evidence_id, caption=None):
    if not evidence_id:
        return
    try:
        ev = svc.get_evidence(conn(), actor(), evidence_id)
    except PermissionDenied:
        st.caption("Evidence attached (not visible to you).")
        return
    if not ev:
        return
    if ev["mime_type"].startswith("image/"):
        st.image(ev["data"], caption=caption or ev["filename"], width=260)
    else:
        st.download_button(f"Download {ev['filename']}", ev["data"], file_name=ev["filename"],
                           mime=ev["mime_type"], key=f"ev_{evidence_id}_{caption}")


def can(perm, department_id=None):
    return has(actor(), perm, department_id)
