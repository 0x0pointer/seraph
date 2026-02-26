from datetime import datetime

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    full_name: str
    email: str
    username: str
    password: str = Field(min_length=12, description="Minimum 12 characters")
    turnstile_token: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class OrgInfo(BaseModel):
    id: int
    name: str
    role: str


class UserRead(BaseModel):
    id: int
    username: str
    full_name: str | None = None
    email: str | None = None
    role: str
    org_id: int | None = None
    team_id: int | None = None
    created_at: datetime | None = None
    orgs: list[OrgInfo] = []

    model_config = {"from_attributes": True}


class ApiTokenResponse(BaseModel):
    api_token: str
    created: bool  # True = freshly generated, False = already existed
