"""Admin endpoints for Aquila-Atlas.

License status, user management, and repository membership management.
All endpoints require the ``admin`` role (or pass through when auth is
disabled).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from aquila_atlas.api.deps import AdminUser, Svc  # noqa: TC001
from aquila_atlas.api.models import (
    AddRepoMemberRequest,
    LicenseStatus,
    PurgeResult,
    QdrantStat,
    RepoAdminInfo,
    RepoMemberInfo,
    SystemStatsResponse,
    TableStat,
    UserInfo,
    UserUpdateRequest,
)

router = APIRouter(tags=["Admin"])


def _get_auth_store(request: Request) -> Any:
    """Return auth store or raise 503."""
    store = getattr(request.app.state, "auth_store", None)
    if store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Auth store unavailable — check PostgreSQL connection",
        )
    return store


# ---------------------------------------------------------------------------
# License
# ---------------------------------------------------------------------------


@router.get(
    "/admin/license",
    response_model=LicenseStatus,
    summary="Instance license status",
    description="Return current license validity, seat counts, and expiry date.",
)
def get_license(request: Request, _admin: AdminUser) -> LicenseStatus:
    auth_store = _get_auth_store(request)
    lic = auth_store.load_license()
    if lic is None:
        return LicenseStatus(valid=False)

    now_utc = datetime.now(tz=UTC)
    expires_at = lic["expires_at"]
    valid = expires_at > now_utc if expires_at else False
    seats_used = auth_store.count_active_users()
    max_seats = lic["max_seats"]

    return LicenseStatus(
        valid=valid,
        customer_id=lic["customer_id"],
        customer_name=lic["customer_name"],
        max_seats=max_seats,
        seats_used=seats_used,
        seats_available=max(0, max_seats - seats_used),
        expires_at=expires_at.isoformat() if expires_at else "",
    )


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


@router.get(
    "/admin/users",
    response_model=list[UserInfo],
    summary="List all users",
    description="Return all provisioned users.",
)
def list_users(request: Request, _admin: AdminUser) -> list[UserInfo]:
    auth_store = _get_auth_store(request)
    users = auth_store.list_users()
    return [
        UserInfo(
            user_id=u["id"],
            email=u["email"],
            display_name=u["display_name"],
            role=u["role"],
            auth_mode=u["auth_mode"],
            is_active=u["is_active"],
            created_at=u["created_at"] or "",
            last_seen_at=u["last_seen_at"],
        )
        for u in users
    ]


@router.get(
    "/admin/users/{user_id}",
    response_model=UserInfo,
    summary="Get a single user",
)
def get_user(user_id: str, request: Request, _admin: AdminUser) -> UserInfo:
    auth_store = _get_auth_store(request)
    user = auth_store.get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return UserInfo(
        user_id=user["id"],
        email=user["email"],
        display_name=user["display_name"],
        role=user["role"],
        auth_mode=user["auth_mode"],
        is_active=user["is_active"],
        created_at=user["created_at"] or "",
        last_seen_at=user["last_seen_at"],
    )


@router.patch(
    "/admin/users/{user_id}",
    response_model=UserInfo,
    summary="Update a user",
    description="Update is_active, role, or display_name.",
)
def update_user(
    user_id: str, body: UserUpdateRequest, request: Request, _admin: AdminUser
) -> UserInfo:
    auth_store = _get_auth_store(request)
    user = auth_store.get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    kwargs = {k: v for k, v in body.model_dump().items() if v is not None}
    if kwargs:
        auth_store.update_user(user_id, **kwargs)
        # If deactivating, revoke all sessions
        if kwargs.get("is_active") is False:
            auth_store.delete_user_sessions(user_id)

    updated = auth_store.get_user_by_id(user_id)
    assert updated is not None
    return UserInfo(
        user_id=updated["id"],
        email=updated["email"],
        display_name=updated["display_name"],
        role=updated["role"],
        auth_mode=updated["auth_mode"],
        is_active=updated["is_active"],
        created_at=updated["created_at"] or "",
        last_seen_at=updated["last_seen_at"],
    )


@router.delete(
    "/admin/users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a user",
    description="Permanently delete a user, freeing their seat.",
)
def delete_user(user_id: str, request: Request, _admin: AdminUser) -> None:
    auth_store = _get_auth_store(request)
    user = auth_store.get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    # Revoke sessions first
    auth_store.delete_user_sessions(user_id)
    auth_store.delete_user(user_id)


# ---------------------------------------------------------------------------
# Repo membership
# ---------------------------------------------------------------------------


@router.post(
    "/repos/{repo_id}/members",
    response_model=RepoMemberInfo,
    status_code=status.HTTP_201_CREATED,
    summary="Add a repo member",
    description="Grant a user access to a repository (owner/member/viewer).",
)
def add_repo_member(
    repo_id: str, body: AddRepoMemberRequest, request: Request, _admin: AdminUser
) -> RepoMemberInfo:
    auth_store = _get_auth_store(request)
    user = auth_store.get_user_by_email(body.email)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No user with email '{body.email}'",
        )
    valid_roles = {"owner", "member", "viewer"}
    if body.role not in valid_roles:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role '{body.role}'. Must be one of: {', '.join(sorted(valid_roles))}",
        )
    auth_store.add_repo_member(repo_id, user["id"], body.role)
    return RepoMemberInfo(
        user_id=user["id"],
        email=user["email"],
        display_name=user["display_name"],
        role=body.role,
    )


@router.get(
    "/repos/{repo_id}/members",
    response_model=list[RepoMemberInfo],
    summary="List repo members",
)
def list_repo_members(repo_id: str, request: Request, _admin: AdminUser) -> list[RepoMemberInfo]:
    auth_store = _get_auth_store(request)
    members = auth_store.list_repo_members(repo_id)
    return [
        RepoMemberInfo(
            user_id=m["user_id"],
            email=m["email"],
            display_name=m["display_name"],
            role=m["role"],
        )
        for m in members
    ]


@router.delete(
    "/repos/{repo_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a repo member",
)
def remove_repo_member(repo_id: str, user_id: str, request: Request, _admin: AdminUser) -> None:
    auth_store = _get_auth_store(request)
    removed = auth_store.remove_repo_member(repo_id, user_id)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Membership not found",
        )


# ---------------------------------------------------------------------------
# All repos with stats (admin view)
# ---------------------------------------------------------------------------


@router.get(
    "/admin/repos",
    response_model=list[RepoAdminInfo],
    summary="List all repos with stats (admin)",
    description="Returns every ingested repo with graph + vector stats. Admin only.",
)
def admin_list_repos(request: Request, svc: Svc, _admin: AdminUser) -> list[RepoAdminInfo]:
    results: list[RepoAdminInfo] = []
    for repo_id in svc.list_repo_ids():
        raw = svc.get_repo_stats(repo_id)
        results.append(
            RepoAdminInfo(
                repo_id=repo_id,
                graph_nodes=(
                    raw.get("Repository", 0)
                    + raw.get("File", 0)
                    + raw.get("Class", 0)
                    + raw.get("Function", 0)
                    + raw.get("Method", 0)
                ),
                graph_relationships=raw.get("relationships", 0),
                vector_chunks=raw.get("chunks", 0),
                files=raw.get("files", 0),
                commit_sha=svc.get_repo_commit_sha(repo_id),
            )
        )
    return results


# ---------------------------------------------------------------------------
# System stats — Qdrant + PostgreSQL
# ---------------------------------------------------------------------------


@router.get(
    "/admin/system/stats",
    response_model=SystemStatsResponse,
    summary="System infrastructure stats",
    description="Returns Qdrant collection info and PostgreSQL table row counts.",
)
def system_stats(request: Request, svc: Svc, _admin: AdminUser) -> SystemStatsResponse:
    # --- Qdrant ---
    qdrant_stats: list[QdrantStat] = []
    try:
        client = svc.vector._client
        collections = client.get_collections().collections
        for col in collections:
            info = client.get_collection(col.name)
            qdrant_stats.append(
                QdrantStat(
                    collection_name=col.name,
                    vectors_count=info.indexed_vectors_count or 0,
                    points_count=info.points_count or 0,
                    segments_count=info.segments_count or 0,
                    status=str(info.status),
                )
            )
    except Exception:  # noqa: BLE001
        pass

    # --- PostgreSQL ---
    pg_stats: list[TableStat] = []
    auth_store = getattr(request.app.state, "auth_store", None)
    if auth_store is not None:
        _AQUILA_TABLES = [
            "aquila_users",
            "aquila_auth_sessions",
            "aquila_instance_license",
            "aquila_repo_members",
            "aquila_sessions",
            "aquila_docs",
            "aquila_test_sets",
            "aquila_security_scans",
        ]
        try:
            conn = auth_store._live()
            for tbl in _AQUILA_TABLES:
                try:
                    row = conn.execute(
                        f"SELECT COUNT(*) FROM {tbl}"  # noqa: S608
                    ).fetchone()
                    count = row[0] if row else 0
                    size_row = conn.execute("SELECT pg_relation_size(%s)", (tbl,)).fetchone()
                    size = size_row[0] if size_row else None
                    pg_stats.append(TableStat(table_name=tbl, row_count=count, size_bytes=size))
                except Exception:  # noqa: BLE001
                    pg_stats.append(TableStat(table_name=tbl, row_count=-1))
        except Exception:  # noqa: BLE001
            pass

    return SystemStatsResponse(qdrant=qdrant_stats, postgres=pg_stats)


# ---------------------------------------------------------------------------
# Maintenance purge
# ---------------------------------------------------------------------------


@router.post(
    "/admin/maintenance/purge",
    response_model=PurgeResult,
    summary="Purge expired rows from TTL tables",
    description="Deletes expired sessions, docs, tests, security scans, and auth sessions.",
)
def maintenance_purge(request: Request, _admin: AdminUser) -> PurgeResult:
    sessions_purged = 0
    doc_rows_purged = 0
    test_rows_purged = 0
    security_rows_purged = 0
    auth_sessions_purged = 0

    # All stores use autocommit=True connections; _live() returns the connection directly.
    store = getattr(request.app.state, "store", None)
    if store is not None:
        try:
            cur = store._live().execute(
                "DELETE FROM aquila_sessions WHERE expires_at < NOW() RETURNING session_id"
            )
            sessions_purged = len(cur.fetchall())
        except Exception:  # noqa: BLE001
            pass

    doc_store = getattr(request.app.state, "doc_store", None)
    if doc_store is not None:
        try:
            cur = doc_store._live().execute(
                "DELETE FROM aquila_docs WHERE expires_at < NOW() RETURNING job_id"
            )
            doc_rows_purged = len(cur.fetchall())
        except Exception:  # noqa: BLE001
            pass

    test_store = getattr(request.app.state, "test_store", None)
    if test_store is not None:
        try:
            cur = test_store._live().execute(
                "DELETE FROM aquila_test_sets WHERE expires_at < NOW() RETURNING job_id"
            )
            test_rows_purged = len(cur.fetchall())
        except Exception:  # noqa: BLE001
            pass

    security_store = getattr(request.app.state, "security_store", None)
    if security_store is not None:
        try:
            cur = security_store._live().execute(
                "DELETE FROM aquila_security_scans WHERE expires_at < NOW() RETURNING job_id"
            )
            security_rows_purged = len(cur.fetchall())
        except Exception:  # noqa: BLE001
            pass

    auth_store = getattr(request.app.state, "auth_store", None)
    if auth_store is not None:
        try:
            cur = auth_store._live().execute(
                "DELETE FROM aquila_auth_sessions WHERE expires_at < NOW() RETURNING id"
            )
            auth_sessions_purged = len(cur.fetchall())
        except Exception:  # noqa: BLE001
            pass

    return PurgeResult(
        sessions_purged=sessions_purged,
        doc_rows_purged=doc_rows_purged,
        test_rows_purged=test_rows_purged,
        security_rows_purged=security_rows_purged,
        auth_sessions_purged=auth_sessions_purged,
    )
