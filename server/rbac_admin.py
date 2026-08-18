"""RBAC data access control — Python layer for Email/Drive access management.

Manages who can access whose emails and drives based on their role/team.
Works with org_db.py to enforce multi-layer isolation.

Functions:
  - set_member_email_access(org_id, email, access_level)
  - set_member_drive_access(org_id, email, access_level)
  - get_member_access(org_id, email) -> {email_access, drive_access}
  - list_member_access(org_id) -> [(email, email_access, drive_access)]
  - log_data_access(actor_email, action, target_email, resource_type, result)
"""
from __future__ import annotations
from datetime import datetime

_DB_READ = None
_DB_WRITE = None

def configure(*, db_read, db_write):
    """Wire in db_read/db_write callables."""
    global _DB_READ, _DB_WRITE
    if not callable(db_read) or not callable(db_write):
        raise TypeError("db_read and db_write must be callable")
    _DB_READ = db_read
    _DB_WRITE = db_write


# Access level hierarchy: none < own < team < all
ACCESS_LEVELS = {
    "none": 0,      # No access
    "own": 1,       # Only own emails/drive
    "team": 2,      # Own + direct reports / team members
    "all": 3,       # All members' data
}

VALID_RESOURCE_TYPES = ("email", "drive")


def set_member_email_access(org_id, member_email, access_level):
    """Set email access level for a member.

    access_level: "none" | "own" | "team" | "all"

    Returns: True on success, False on error
    """
    if access_level not in ACCESS_LEVELS:
        return False

    # Upsert into member_rbac_access table
    _DB_WRITE(
        "INSERT INTO member_rbac_access "
        "(org_id, member_email, email_access, updated_at) "
        "VALUES (%s, %s, %s, NOW()) "
        "ON DUPLICATE KEY UPDATE email_access=%s, updated_at=NOW()",
        (org_id, member_email.lower(), access_level, access_level))
    return True


def set_member_drive_access(org_id, member_email, access_level):
    """Set Drive access level for a member.

    access_level: "none" | "own" | "team" | "all"

    Returns: True on success, False on error
    """
    if access_level not in ACCESS_LEVELS:
        return False

    _DB_WRITE(
        "INSERT INTO member_rbac_access "
        "(org_id, member_email, drive_access, updated_at) "
        "VALUES (%s, %s, %s, NOW()) "
        "ON DUPLICATE KEY UPDATE drive_access=%s, updated_at=NOW()",
        (org_id, member_email.lower(), access_level, access_level))
    return True


def get_member_access(org_id, member_email):
    """Get email + drive access levels for a member.

    Returns: {
        "email_access": "own" | "team" | "all",
        "drive_access": "own" | "team" | "all",
        "updated_at": "2026-08-18T..."
    }
    or None if not found (defaults to "own")
    """
    row = _DB_READ(
        "SELECT email_access, drive_access, updated_at "
        "FROM member_rbac_access "
        "WHERE org_id=%s AND member_email=%s",
        (org_id, member_email.lower()))

    if row:
        return {
            "email_access": row.get("email_access") or "own",
            "drive_access": row.get("drive_access") or "own",
            "updated_at": row.get("updated_at"),
        }

    # Default: members can see their own data
    return {
        "email_access": "own",
        "drive_access": "own",
        "updated_at": None,
    }


def list_member_access(org_id):
    """List email + drive access for all members in org.

    Returns: [
        {
            "member_email": "user@example.com",
            "email_access": "own",
            "drive_access": "own",
            "updated_at": "2026-08-18T..."
        },
        ...
    ]
    """
    rows = _DB_READ(
        "SELECT member_email, email_access, drive_access, updated_at "
        "FROM member_rbac_access "
        "WHERE org_id=%s "
        "ORDER BY member_email",
        (org_id,)) or []

    result = []
    for row in rows:
        result.append({
            "member_email": row.get("member_email"),
            "email_access": row.get("email_access") or "own",
            "drive_access": row.get("drive_access") or "own",
            "updated_at": row.get("updated_at"),
        })
    return result


def log_data_access(actor_email, action, target_email, resource_type, result="ok"):
    """Log a data access event for audit trail.

    action: "search_email_semantic" | "list_recent_emails" | "search_drive_semantic" | etc.
    resource_type: "email" | "drive"
    result: "ok" | "denied" | "error"
    """
    if resource_type not in VALID_RESOURCE_TYPES:
        return False

    _DB_WRITE(
        "INSERT INTO rbac_access_log "
        "(actor_email, action, target_email, resource_type, result, timestamp) "
        "VALUES (%s, %s, %s, %s, %s, NOW())",
        (actor_email.lower(), action, target_email.lower() if target_email else None,
         resource_type, result))
    return True


def get_access_log(org_id, limit=50, days_back=7):
    """Get recent access log entries.

    Returns: [
        {
            "actor_email": "user@example.com",
            "action": "search_email_semantic",
            "target_email": "manager@example.com",
            "resource_type": "email",
            "result": "ok",
            "timestamp": "2026-08-18T10:30:00Z"
        },
        ...
    ]
    """
    rows = _DB_READ(
        "SELECT actor_email, action, target_email, resource_type, result, timestamp "
        "FROM rbac_access_log "
        "WHERE timestamp > DATE_SUB(NOW(), INTERVAL %s DAY) "
        "ORDER BY timestamp DESC LIMIT %s",
        (days_back, limit)) or []

    result = []
    for row in rows:
        result.append({
            "actor_email": row.get("actor_email"),
            "action": row.get("action"),
            "target_email": row.get("target_email"),
            "resource_type": row.get("resource_type"),
            "result": row.get("result"),
            "timestamp": row.get("timestamp"),
        })
    return result


def get_accessible_members(org_id, requester_email, resource_type):
    """Get list of members whose data the requester can access.

    resource_type: "email" | "drive"

    Returns: [email1, email2, ...] (sorted)
    """
    if resource_type not in VALID_RESOURCE_TYPES:
        return []

    # Get requester's access level
    access = get_member_access(org_id, requester_email)
    access_col = f"{resource_type}_access"
    requester_level = access.get(access_col) or "own"

    # none = no access
    if requester_level == "none":
        return []

    # own = only self
    if requester_level == "own":
        return [requester_email.lower()]

    # team = self + direct reports
    if requester_level == "team":
        members = _DB_READ(
            "SELECT email FROM org_members "
            "WHERE org_id=%s AND status='active' "
            "ORDER BY email",
            (org_id,)) or []

        # Find requester's team
        requester_row = _DB_READ(
            "SELECT department FROM org_members "
            "WHERE org_id=%s AND email=%s",
            (org_id, requester_email.lower()))

        if not requester_row:
            return []

        dept = requester_row.get("department")
        accessible = [requester_email.lower()]

        # Add team members (same department)
        if dept:
            team_members = _DB_READ(
                "SELECT email FROM org_members "
                "WHERE org_id=%s AND department=%s AND status='active'",
                (org_id, dept)) or []
            accessible.extend([m["email"].lower() for m in team_members])

        return sorted(set(accessible))

    # all = everyone
    members = _DB_READ(
        "SELECT email FROM org_members "
        "WHERE org_id=%s AND status='active' "
        "ORDER BY email",
        (org_id,)) or []
    return [m["email"].lower() for m in members]
