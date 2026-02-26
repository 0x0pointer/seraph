from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.auth import get_current_user
from app.core.database import get_session
from app.models.team import Team
from app.models.user import User
from app.services.event_service import log_event

router = APIRouter(prefix="/teams", tags=["teams"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class TeamCreate(BaseModel):
    name: str

class TeamRename(BaseModel):
    name: str

class TeamRead(BaseModel):
    id: int
    name: str
    org_id: int
    created_by_username: str | None
    member_count: int

class MemberRead(BaseModel):
    id: int
    username: str
    full_name: str | None
    email: str | None
    role: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _require_org_admin(user: User) -> User:
    if user.role not in ("admin", "org_admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Org admin required")
    if user.org_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You are not in an organization")
    return user

def _require_org_member(user: User) -> User:
    if user.org_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You are not in an organization")
    return user

async def _get_team(team_id: int, org_id: int, session: AsyncSession) -> Team:
    result = await session.execute(
        select(Team).where(Team.id == team_id, Team.org_id == org_id)
    )
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    return team


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("", response_model=list[TeamRead])
async def list_teams(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    _require_org_member(current_user)
    result = await session.execute(
        select(Team).where(Team.org_id == current_user.org_id).order_by(Team.created_at)
    )
    teams = result.scalars().all()

    # Attach member counts
    out = []
    for t in teams:
        count_result = await session.execute(
            select(func.count(User.id)).where(User.team_id == t.id)
        )
        out.append(TeamRead(
            id=t.id, name=t.name, org_id=t.org_id,
            created_by_username=t.created_by_username,
            member_count=count_result.scalar_one(),
        ))
    return out


@router.post("", response_model=TeamRead, status_code=status.HTTP_201_CREATED)
async def create_team(
    data: TeamCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    _require_org_admin(current_user)
    team = Team(
        name=data.name.strip(),
        org_id=current_user.org_id,
        created_by_username=current_user.username,
    )
    session.add(team)
    await session.flush()
    await log_event(session, event_type="team.created",
        actor_id=current_user.id, actor_username=current_user.username,
        target_type="team", target_id=team.id, target_name=team.name,
        details={"org_id": current_user.org_id})
    await session.commit()
    await session.refresh(team)
    return TeamRead(id=team.id, name=team.name, org_id=team.org_id,
                    created_by_username=team.created_by_username, member_count=0)


@router.put("/{team_id}", response_model=TeamRead)
async def rename_team(
    team_id: int,
    data: TeamRename,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    _require_org_admin(current_user)
    team = await _get_team(team_id, current_user.org_id, session)
    team.name = data.name.strip()
    session.add(team)
    await log_event(session, event_type="team.renamed",
        actor_id=current_user.id, actor_username=current_user.username,
        target_type="team", target_id=team.id, target_name=team.name, details={})
    await session.commit()

    count_result = await session.execute(select(func.count(User.id)).where(User.team_id == team.id))
    return TeamRead(id=team.id, name=team.name, org_id=team.org_id,
                    created_by_username=team.created_by_username,
                    member_count=count_result.scalar_one())


@router.delete("/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_team(
    team_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    _require_org_admin(current_user)
    team = await _get_team(team_id, current_user.org_id, session)

    # Unassign all members from this team
    members_result = await session.execute(select(User).where(User.team_id == team.id))
    for member in members_result.scalars().all():
        member.team_id = None
        session.add(member)

    await log_event(session, event_type="team.deleted",
        actor_id=current_user.id, actor_username=current_user.username,
        target_type="team", target_id=team.id, target_name=team.name, details={})
    await session.delete(team)
    await session.commit()


@router.get("/{team_id}/members", response_model=list[MemberRead])
async def list_team_members(
    team_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    _require_org_member(current_user)
    await _get_team(team_id, current_user.org_id, session)  # verify team belongs to org
    result = await session.execute(select(User).where(User.team_id == team_id))
    return [MemberRead(id=u.id, username=u.username, full_name=u.full_name,
                       email=u.email, role=u.role)
            for u in result.scalars().all()]


@router.patch("/{team_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def assign_member(
    team_id: int,
    user_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Assign a user to this team (removes from any previous team)."""
    _require_org_admin(current_user)
    team = await _get_team(team_id, current_user.org_id, session)

    user_result = await session.execute(
        select(User).where(User.id == user_id, User.org_id == current_user.org_id)
    )
    target = user_result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found in this org")

    target.team_id = team.id
    session.add(target)
    await log_event(session, event_type="team.member_added",
        actor_id=current_user.id, actor_username=current_user.username,
        target_type="user", target_id=target.id, target_name=target.username,
        details={"team_id": team.id, "team_name": team.name})
    await session.commit()


@router.delete("/{team_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    team_id: int,
    user_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Remove a user from this team."""
    _require_org_admin(current_user)
    await _get_team(team_id, current_user.org_id, session)

    user_result = await session.execute(
        select(User).where(User.id == user_id, User.team_id == team_id)
    )
    target = user_result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User is not in this team")

    target.team_id = None
    session.add(target)
    await log_event(session, event_type="team.member_removed",
        actor_id=current_user.id, actor_username=current_user.username,
        target_type="user", target_id=target.id, target_name=target.username,
        details={"team_id": team_id})
    await session.commit()
