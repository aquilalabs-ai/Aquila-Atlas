"""LDAP / Active Directory authentication for Aquila-Atlas.

Used when ``AUTH_MODE`` is ``ldap`` or ``both``.  On first successful login the
caller is responsible for upserting the user record in ``AuthStore``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aquila_atlas.config import Settings

_log = logging.getLogger("aquila.auth.ldap")


def ldap_authenticate(username: str, password: str, settings: Settings) -> dict | None:  # type: ignore[type-arg]
    """Attempt to authenticate *username* / *password* against the configured LDAP server.

    Parameters
    ----------
    username:
        The value substituted into ``settings.ldap_user_filter`` in place of
        ``{username}``.  Typically the user's e-mail address or SAM account
        name, depending on the filter template.
    password:
        Plain-text password to bind with.
    settings:
        Application settings carrying LDAP connection details.

    Returns
    -------
    dict | None
        On success: ``{"email": str, "display_name": str, "dn": str}``.
        On failure (bad credentials, user not found, group check failed):
        ``None``.
    """
    from ldap3 import (  # noqa: PLC0415
        AUTO_BIND_NO_TLS,
        SIMPLE,
        SUBTREE,
        Connection,
        Server,
    )

    if not settings.ldap_url:
        _log.error("LDAP authentication requested but LDAP_URL is not configured")
        return None

    server = Server(settings.ldap_url, connect_timeout=5)

    # --- Step 1: service-account bind to locate the user DN ----------------
    try:
        svc_conn = Connection(
            server,
            user=settings.ldap_bind_dn,
            password=settings.ldap_bind_password,
            authentication=SIMPLE,
            auto_bind=AUTO_BIND_NO_TLS,
            raise_exceptions=True,
        )
    except Exception:
        _log.warning("LDAP service-account bind failed", exc_info=True)
        return None

    search_filter = settings.ldap_user_filter.replace("{username}", username)
    try:
        svc_conn.search(
            search_base=settings.ldap_user_base,
            search_filter=search_filter,
            search_scope=SUBTREE,
            attributes=["cn", "mail", "displayName", "distinguishedName", "memberOf"],
        )
    except Exception:
        _log.warning("LDAP user search failed for %s", username, exc_info=True)
        svc_conn.unbind()
        return None

    entries = svc_conn.entries
    svc_conn.unbind()

    if not entries:
        _log.debug("LDAP: no user found matching filter %s", search_filter)
        return None

    entry = entries[0]
    user_dn: str = entry.entry_dn

    # --- Step 2: optional group membership check ----------------------------
    if settings.ldap_required_group:
        member_of: list[str] = []
        import contextlib  # noqa: PLC0415

        with contextlib.suppress(Exception):
            member_of = [str(g) for g in entry.memberOf]
        group_dn_lower = settings.ldap_required_group.lower()
        if not any(g.lower() == group_dn_lower for g in member_of):
            _log.debug(
                "LDAP: user %s is not a member of required group %s",
                user_dn,
                settings.ldap_required_group,
            )
            return None

    # --- Step 3: bind as the located user to verify the password ------------
    try:
        user_conn = Connection(
            server,
            user=user_dn,
            password=password,
            authentication=SIMPLE,
            auto_bind=AUTO_BIND_NO_TLS,
            raise_exceptions=True,
        )
        user_conn.unbind()
    except Exception:
        _log.debug("LDAP: password verification failed for %s", user_dn)
        return None

    # --- Step 4: extract useful attributes ----------------------------------
    def _attr(name: str) -> str:
        try:
            val = getattr(entry, name)
            return str(val) if val else ""
        except Exception:
            return ""

    email = _attr("mail") or username
    display_name = _attr("displayName") or _attr("cn") or username

    return {"email": email, "display_name": display_name, "dn": user_dn}
