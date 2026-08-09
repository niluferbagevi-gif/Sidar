"""Validated request payload models shared by Sidar's HTTP route factories."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    """Payload accepted when a user account is registered."""

    username: str = Field(..., max_length=64)
    password: str = Field(..., max_length=128)
    tenant_id: str = Field(default="default", min_length=1, max_length=64)


class LoginRequest(BaseModel):
    """Credentials accepted by the login endpoint."""

    username: str = Field(..., max_length=64)
    password: str = Field(..., max_length=128)


class PromptUpsertRequest(BaseModel):
    """Payload for creating or updating a role prompt."""

    role_name: str = Field(..., min_length=1, max_length=64)
    prompt_text: str = Field(..., min_length=1)
    activate: bool = Field(default=True)


class PromptActivateRequest(BaseModel):
    """Payload selecting the prompt revision to activate."""

    prompt_id: int = Field(..., gt=0)


class PolicyUpsertRequest(BaseModel):
    """Payload for an access-policy rule upsert."""

    user_id: str = Field(..., min_length=1, max_length=128)
    tenant_id: str = Field(default="default", min_length=1, max_length=64)
    resource_type: str = Field(..., min_length=1, max_length=64)
    resource_id: str = Field(default="*", min_length=1, max_length=256)
    action: str = Field(..., min_length=1, max_length=64)
    effect: str = Field(default="allow", min_length=1, max_length=8)


class AgentPluginRegisterRequest(BaseModel):
    """Payload for registering an agent plugin from source."""

    role_name: str = Field(..., min_length=2, max_length=64)
    source_code: str = Field(..., min_length=1)
    class_name: str | None = Field(default=None, min_length=1, max_length=128)
    capabilities: list[str] = Field(default_factory=list)
    description: str = Field(default="", max_length=512)
    version: str = Field(default="1.0.0", max_length=32)


class PluginMarketplaceInstallRequest(BaseModel):
    """Payload selecting a marketplace plugin for installation."""

    plugin_id: str = Field(..., min_length=2, max_length=64)


class SwarmTaskRequest(BaseModel):
    """One task submitted to the swarm orchestrator."""

    goal: str = Field(..., min_length=1)
    intent: str = Field(default="mixed", min_length=1, max_length=64)
    context: dict[str, str] = Field(default_factory=dict)
    preferred_agent: str | None = Field(default=None, max_length=64)


class SwarmExecuteRequest(BaseModel):
    """Payload controlling parallel or pipeline swarm execution."""

    mode: str = Field(default="parallel", pattern="^(parallel|pipeline)$")
    tasks: list[SwarmTaskRequest] = Field(..., min_length=1)
    session_id: str = Field(default="", max_length=128)
    max_concurrency: int = Field(default=4, ge=1, le=16)
