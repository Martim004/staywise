"""Verified Google OIDC identity for StayWise.

Streamlit manages the OIDC redirect and protected sign-in cookie. StayWise
never receives or stores a Google password or OAuth access token.
"""

from __future__ import annotations

from typing import Any

import streamlit as st


def auth_is_configured() -> bool:
    try:
        config = st.secrets.get("auth", {})
        required = ("redirect_uri", "cookie_secret", "client_id", "client_secret", "server_metadata_url")
        return all(str(config.get(key, "")).strip() for key in required)
    except Exception:
        return False


def current_user() -> dict[str, Any] | None:
    """Return only the identity claims verified by Streamlit's OIDC handler."""
    try:
        if not st.user.is_logged_in:
            return None
        claims = dict(st.user)
        subject = str(claims.get("sub", "")).strip()
        email = str(claims.get("email", "")).strip()
        if not subject or not email or claims.get("email_verified") is False:
            return None
        return {
            "id": subject,
            "email": email,
            "name": str(claims.get("name") or ""),
            "provider": "Google",
            "created_at": None,
        }
    except Exception:
        return None


def sign_in() -> None:
    """Start Streamlit's configured OpenID Connect login flow."""
    st.login()


def sign_out() -> None:
    st.logout()
