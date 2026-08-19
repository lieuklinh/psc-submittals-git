"""
Auth dependency — DEV-MODE ONLY, matching the Streamlit app's current
security model exactly (see pscc-submittals-agent/app.py: `_auth_configured
= False`, manual name/email entry, no verification).

The client sends the signed-in user's email/name via the X-User-Email /
X-User-Name headers (set once at "login" and stored in the browser, same
idea as st.session_state.dev_user_email). There is no password check and
no token signing here, same as today's Streamlit app — this is NOT a
security regression, it's parity. Swapping this for real Microsoft Entra
ID / Azure AD auth (the Streamlit app's `st.login()` path, currently
disabled pending credentials) is tracked as follow-up work in the README.
"""

from fastapi import Header, HTTPException

from . import db


def get_current_user(
    x_user_email: str = Header(..., alias="X-User-Email"),
    x_user_name: str = Header("", alias="X-User-Name"),
):
    email = x_user_email.strip().lower()
    if not email:
        raise HTTPException(401, "X-User-Email header is required")

    existing = db.get_user_by_email(email)
    user_id = existing["id"] if existing else email
    # Only overwrite the stored name when the caller actually sent one —
    # most requests after the initial "login" won't resend X-User-Name, and
    # falling back to the email in that case would clobber the real name
    # on every subsequent call.
    name = x_user_name.strip() or (existing["name"] if existing else email)
    db.upsert_user(user_id, email, name, role=(existing or {}).get("role", "member"))
    return {"id": user_id, "email": email, "name": name}
