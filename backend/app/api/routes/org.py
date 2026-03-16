"""
Organization management routes.
- Org admins (role="org_admin") manage their own org's members & invites.
- Super admins (role="admin") can manage all orgs via /admin/orgs.
"""
import secrets
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import delete, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.auth import get_current_user
from app.core.database import get_session
from app.models.organization import Organization
from app.models.org_invite import OrgInvite
from app.models.user import User
from app.services.event_service import log_event

# Annotated dependency types for FastAPI
SessionDep = Annotated[AsyncSession, Depends(get_session)]

router = APIRouter(prefix="/org", tags=["org"])


# ── Permission helpers ────────────────────────────────────────────────────────

async def require_org_member(current_user: User = Depends(get_current_user)) -> User:
    """Any user that belongs to an org."""
    if not current_user.org_id:
        raise HTTPException(status_code=403, detail="You are not part of an organization")
    return current_user


async def require_org_admin(current_user: User = Depends(get_current_user)) -> User:
    """Must be org_admin (or platform admin) with an org."""
    if current_user.role == "admin":
        return current_user  # superadmin can do everything
    if current_user.role != "org_admin":
        raise HTTPException(status_code=403, detail="Organization admin access required")
    if not current_user.org_id:
        raise HTTPException(status_code=403, detail="You are not part of an organization")
    return current_user


def _org_id_for(user: User) -> int:
    """Return the org_id to scope queries to (for org_admin it's their own org)."""
    if user.org_id is None:
        raise HTTPException(status_code=403, detail="No organization context")
    return user.org_id


# Annotated dependency types for user injection
CurrentUser = Annotated[User, Depends(get_current_user)]
OrgMember = Annotated[User, Depends(require_org_member)]
OrgAdmin = Annotated[User, Depends(require_org_admin)]


# ── Org info ──────────────────────────────────────────────────────────────────

@router.get("")
async def get_my_org(
    session: SessionDep,
    current_user: OrgMember,
):
    """Return current user's organization details."""
    org = (await session.execute(
        select(Organization).where(Organization.id == current_user.org_id)
    )).scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    member_count = (await session.execute(
        select(func.count(User.id)).where(User.org_id == org.id)
    )).scalar_one()

    owner = None
    if org.owner_id:
        owner = (await session.execute(
            select(User).where(User.id == org.owner_id)
        )).scalar_one_or_none()

    return {
        "id": org.id,
        "name": org.name,
        "created_at": org.created_at.isoformat() if org.created_at else None,
        "owner_id": org.owner_id,
        "owner_username": owner.username if owner else None,
        "member_count": member_count,
    }


class CreateOrgRequest(BaseModel):
    name: str


@router.post("", status_code=201)
async def create_my_org(
    data: CreateOrgRequest,
    session: SessionDep,
    current_user: CurrentUser,
):
    """Any authenticated user without an org can create one and become its admin."""
    if current_user.org_id:
        raise HTTPException(status_code=400, detail="You are already part of an organization")

    name = data.name.strip()
    if len(name) < 2:
        raise HTTPException(status_code=422, detail="Organization name must be at least 2 characters")

    from app.models.user_org_membership import UserOrgMembership

    org = Organization(name=name, owner_id=current_user.id)
    session.add(org)
    await session.flush()

    current_user.org_id = org.id
    current_user.role = "org_admin"
    session.add(UserOrgMembership(user_id=current_user.id, org_id=org.id, role="org_admin"))

    await log_event(session, event_type="org.created",
        actor_id=current_user.id, actor_username=current_user.username,
        target_type="org", target_id=org.id, target_name=org.name,
        details={"self_service": True})
    await session.commit()
    await session.refresh(org)
    return {
        "id": org.id,
        "name": org.name,
        "created_at": org.created_at.isoformat() if org.created_at else None,
        "owner_id": org.owner_id,
        "owner_username": current_user.username,
        "member_count": 1,
    }


@router.put("")
async def update_my_org(
    data: dict,
    session: SessionDep,
    current_user: OrgAdmin,
):
    """Update org name (org_admin only)."""
    org_id = _org_id_for(current_user)
    org = (await session.execute(
        select(Organization).where(Organization.id == org_id)
    )).scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    name = (data.get("name") or "").strip()
    if len(name) < 2:
        raise HTTPException(status_code=422, detail="Organization name must be at least 2 characters")

    org.name = name
    await session.commit()
    return {"id": org.id, "name": org.name}


# ── Members ───────────────────────────────────────────────────────────────────

@router.get("/members")
async def list_org_members(
    session: SessionDep,
    current_user: OrgAdmin,
):
    """List all members of the org."""
    org_id = _org_id_for(current_user)
    result = await session.execute(
        select(User)
        .where(User.org_id == org_id)
        .order_by(User.created_at.desc())
    )
    members = result.scalars().all()
    return [
        {
            "id": u.id,
            "username": u.username,
            "full_name": u.full_name,
            "email": u.email,
            "role": u.role,
            "team_id": u.team_id,
            "created_at": u.created_at.isoformat() if u.created_at else None,
        }
        for u in members
    ]


class ChangeMemberRoleRequest(BaseModel):
    role: str  # "org_admin" | "viewer"


@router.patch("/members/{user_id}/role")
async def change_member_role(
    user_id: int,
    data: ChangeMemberRoleRequest,
    session: SessionDep,
    current_user: OrgAdmin,
):
    """Change the role of an org member (cannot change superadmins)."""
    if data.role not in ("org_admin", "viewer"):
        raise HTTPException(status_code=422, detail="Role must be 'org_admin' or 'viewer'")
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot change your own role")

    org_id = _org_id_for(current_user)
    target = (await session.execute(
        select(User).where(User.id == user_id, User.org_id == org_id)
    )).scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="Member not found in your organization")
    if target.role == "admin":
        raise HTTPException(status_code=403, detail="Cannot change a super admin's role")

    from app.models.user_org_membership import UserOrgMembership

    old_role = target.role
    target.role = data.role
    # Keep membership record in sync
    membership = (await session.execute(
        select(UserOrgMembership).where(
            UserOrgMembership.user_id == target.id,
            UserOrgMembership.org_id == org_id,
        )
    )).scalar_one_or_none()
    if membership:
        membership.role = data.role
    await log_event(session, event_type="user.role_changed",
        actor_id=current_user.id, actor_username=current_user.username,
        target_type="user", target_id=target.id, target_name=target.username,
        details={"old_role": old_role, "new_role": data.role, "org_id": org_id})
    await session.commit()
    return {"id": target.id, "role": target.role}


@router.delete("/members/{user_id}", status_code=204)
async def remove_member(
    user_id: int,
    session: SessionDep,
    current_user: OrgAdmin,
):
    """Remove a user from the org (sets their org_id to NULL)."""
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot remove yourself from the organization")

    org_id = _org_id_for(current_user)
    target = (await session.execute(
        select(User).where(User.id == user_id, User.org_id == org_id)
    )).scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="Member not found in your organization")
    if target.role == "admin":
        raise HTTPException(status_code=403, detail="Cannot remove a super admin")

    from app.models.user_org_membership import UserOrgMembership

    await log_event(session, event_type="org.member_removed",
        actor_id=current_user.id, actor_username=current_user.username,
        target_type="user", target_id=target.id, target_name=target.username,
        details={"org_id": org_id})
    target.org_id = None
    if target.role == "org_admin":
        target.role = "viewer"
    # Remove from membership table
    await session.execute(
        delete(UserOrgMembership).where(
            UserOrgMembership.user_id == target.id,
            UserOrgMembership.org_id == org_id,
        )
    )
    await session.commit()


# ── Invites ───────────────────────────────────────────────────────────────────

@router.get("/invites")
async def list_invites(
    session: SessionDep,
    current_user: OrgAdmin,
):
    """List pending (unused) invites for the org."""
    org_id = _org_id_for(current_user)
    result = await session.execute(
        select(OrgInvite)
        .where(OrgInvite.org_id == org_id, OrgInvite.used_at == None)  # noqa: E711
        .order_by(OrgInvite.created_at.desc())
    )
    invites = result.scalars().all()
    return [
        {
            "id": inv.id,
            "email": inv.email,
            "role": inv.role,
            "token": inv.token,
            "invited_by_username": inv.invited_by_username,
            "created_at": inv.created_at.isoformat() if inv.created_at else None,
        }
        for inv in invites
    ]


class CreateInviteRequest(BaseModel):
    email: str
    role: str = "viewer"  # "org_admin" | "viewer"


@router.post("/invite", status_code=201)
async def create_invite(
    data: CreateInviteRequest,
    session: SessionDep,
    current_user: OrgAdmin,
):
    """Create an invite link for a new org member."""
    if data.role not in ("org_admin", "viewer"):
        raise HTTPException(status_code=422, detail="Role must be 'org_admin' or 'viewer'")
    if "@" not in data.email:
        raise HTTPException(status_code=422, detail="Invalid email address")

    org_id = _org_id_for(current_user)

    # Check not already a member
    existing_user = (await session.execute(
        select(User).where(User.email == data.email.lower().strip(), User.org_id == org_id)
    )).scalar_one_or_none()
    if existing_user:
        raise HTTPException(status_code=409, detail="This user is already a member of your organization")

    # Revoke any existing pending invite for the same email+org
    old_invite = (await session.execute(
        select(OrgInvite).where(
            OrgInvite.org_id == org_id,
            OrgInvite.email == data.email.lower().strip(),
            OrgInvite.used_at == None,  # noqa: E711
        )
    )).scalar_one_or_none()
    if old_invite:
        await session.delete(old_invite)

    token = secrets.token_urlsafe(32)
    invite = OrgInvite(
        org_id=org_id,
        email=data.email.lower().strip(),
        token=token,
        role=data.role,
        invited_by_id=current_user.id,
        invited_by_username=current_user.username,
    )
    session.add(invite)
    await log_event(session, event_type="org.invite_created",
        actor_id=current_user.id, actor_username=current_user.username,
        target_type="invite", target_id=None, target_name=data.email,
        details={"role": data.role, "org_id": org_id})
    await session.commit()
    await session.refresh(invite)
    return {
        "id": invite.id,
        "email": invite.email,
        "role": invite.role,
        "token": invite.token,
        "created_at": invite.created_at.isoformat() if invite.created_at else None,
    }


@router.delete("/invites/{invite_id}", status_code=204)
async def cancel_invite(
    invite_id: int,
    session: SessionDep,
    current_user: OrgAdmin,
):
    """Cancel a pending invite."""
    org_id = _org_id_for(current_user)
    invite = (await session.execute(
        select(OrgInvite).where(OrgInvite.id == invite_id, OrgInvite.org_id == org_id)
    )).scalar_one_or_none()
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")
    await session.delete(invite)
    await session.commit()


# ── Public: validate invite token ─────────────────────────────────────────────

@router.get("/invite/validate")
async def validate_invite_token(
    session: SessionDep,
    token: str = Query(...),
):
    """Validate an invite token — returns org name + email + role."""
    invite = (await session.execute(
        select(OrgInvite).where(OrgInvite.token == token, OrgInvite.used_at == None)  # noqa: E711
    )).scalar_one_or_none()
    if not invite:
        raise HTTPException(status_code=404, detail="Invalid or already used invite link")

    org = (await session.execute(
        select(Organization).where(Organization.id == invite.org_id)
    )).scalar_one_or_none()

    return {
        "email": invite.email,
        "role": invite.role,
        "org_name": org.name if org else "Unknown",
        "org_id": invite.org_id,
        "invited_by": invite.invited_by_username,
    }


class AcceptInviteRequest(BaseModel):
    token: str
    username: str
    password: str
    full_name: str = ""


@router.post("/invite/accept")
async def accept_invite(
    data: AcceptInviteRequest,
    session: SessionDep,
):
    """Accept an org invite — creates a new user account and joins the org."""
    from app.core.security import hash_password, create_access_token

    invite = (await session.execute(
        select(OrgInvite).where(OrgInvite.token == data.token, OrgInvite.used_at == None)  # noqa: E711
    )).scalar_one_or_none()
    if not invite:
        raise HTTPException(status_code=400, detail="Invalid or already used invite link")

    if len(data.username.strip()) < 3:
        raise HTTPException(status_code=422, detail="Username must be at least 3 characters")
    if len(data.password) < 6:
        raise HTTPException(status_code=422, detail="Password must be at least 6 characters")

    existing = (await session.execute(
        select(User).where(User.username == data.username.strip())
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Username already taken")

    # Check if the email already has an account — if so, just assign org
    existing_by_email = (await session.execute(
        select(User).where(User.email == invite.email)
    )).scalar_one_or_none()

    from app.models.user_org_membership import UserOrgMembership

    if existing_by_email:
        # Assign to org
        existing_by_email.org_id = invite.org_id
        if existing_by_email.role not in ("admin", "org_admin"):
            existing_by_email.role = invite.role
        invite.used_at = datetime.now(timezone.utc)
        # Upsert membership record
        existing_membership = (await session.execute(
            select(UserOrgMembership).where(
                UserOrgMembership.user_id == existing_by_email.id,
                UserOrgMembership.org_id == invite.org_id,
            )
        )).scalar_one_or_none()
        if not existing_membership:
            session.add(UserOrgMembership(
                user_id=existing_by_email.id, org_id=invite.org_id, role=invite.role
            ))
        await session.commit()
        token = create_access_token({"sub": existing_by_email.username, "role": existing_by_email.role})
        return {"access_token": token}

    user = User(
        username=data.username.strip(),
        full_name=data.full_name.strip() if data.full_name else None,
        email=invite.email,
        hashed_password=hash_password(data.password),
        role=invite.role,
        org_id=invite.org_id,
    )
    session.add(user)
    invite.used_at = datetime.now(timezone.utc)
    await session.flush()
    # Create membership record
    session.add(UserOrgMembership(user_id=user.id, org_id=invite.org_id, role=invite.role))
    await log_event(session, event_type="user.registered",
        actor_id=user.id, actor_username=user.username,
        target_type="user", target_id=user.id, target_name=user.username,
        details={"role": invite.role, "org_id": invite.org_id, "via": "invite"})
    await session.commit()
    token = create_access_token({"sub": user.username, "role": user.role})
    return {"access_token": token}
