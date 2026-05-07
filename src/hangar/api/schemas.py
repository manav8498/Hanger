from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

JsonObject = dict[str, Any]


class ErrorBody(BaseModel):
    type: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody


class AgentModel(BaseModel):
    id: str
    speed: str = "standard"


class PermissionPolicy(BaseModel):
    type: str = "always_allow"


class AgentToolDefaultConfig(BaseModel):
    permission_policy: PermissionPolicy = Field(default_factory=PermissionPolicy)


class AgentTool(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str
    default_config: AgentToolDefaultConfig | None = None


class AgentCreateRequest(BaseModel):
    name: str
    model: AgentModel
    system: str | None = None
    description: str | None = None
    tools: list[AgentTool] = Field(default_factory=list)
    skills: list[JsonObject] = Field(default_factory=list)
    mcp_servers: list[JsonObject] = Field(default_factory=list)
    metadata: JsonObject = Field(default_factory=dict)

    @field_validator("tools")
    @classmethod
    def normalize_tools(cls, tools: list[AgentTool]) -> list[AgentTool]:
        return [normalize_agent_tool(tool) for tool in tools]


class AgentPatchRequest(BaseModel):
    name: str | None = None
    model: AgentModel | None = None
    system: str | None = None
    description: str | None = None
    tools: list[AgentTool] | None = None
    skills: list[JsonObject] | None = None
    mcp_servers: list[JsonObject] | None = None
    metadata: JsonObject | None = None

    @field_validator("tools")
    @classmethod
    def normalize_patch_tools(cls, tools: list[AgentTool] | None) -> list[AgentTool] | None:
        if tools is None:
            return None
        return [normalize_agent_tool(tool) for tool in tools]


class AgentResponse(BaseModel):
    id: str
    type: Literal["agent"] = "agent"
    name: str
    model: AgentModel
    system: str | None = None
    description: str | None = None
    tools: list[JsonObject]
    skills: list[JsonObject]
    mcp_servers: list[JsonObject]
    metadata: JsonObject
    version: int
    created_at: str
    updated_at: str
    archived_at: str | None = None


class Packages(BaseModel):
    pip: list[str] = Field(default_factory=list)
    npm: list[str] = Field(default_factory=list)


class UnrestrictedNetworking(BaseModel):
    type: Literal["unrestricted"] = "unrestricted"


class LimitedNetworking(BaseModel):
    type: Literal["limited"] = "limited"
    allowed_hosts: list[str] = Field(default_factory=list)
    allow_mcp_servers: bool = False
    allow_package_managers: bool = False


Networking = Annotated[
    UnrestrictedNetworking | LimitedNetworking,
    Field(discriminator="type"),
]


class CloudEnvironmentConfig(BaseModel):
    type: Literal["cloud"] = "cloud"
    packages: Packages = Field(default_factory=Packages)
    networking: Networking = Field(default_factory=UnrestrictedNetworking)


EnvironmentConfig = Annotated[CloudEnvironmentConfig, Field(discriminator="type")]


class EnvironmentCreateRequest(BaseModel):
    name: str
    config: EnvironmentConfig


class EnvironmentResponse(BaseModel):
    id: str
    type: Literal["environment"] = "environment"
    name: str
    config: CloudEnvironmentConfig
    archived_at: str | None = None
    created_at: str
    updated_at: str


class SessionCreateRequest(BaseModel):
    agent: str | JsonObject
    environment_id: str
    title: str | None = None
    vault_ids: list[str] = Field(default_factory=list)


class SessionResponse(BaseModel):
    id: str
    type: Literal["session"] = "session"
    agent_id: str
    agent_version: int
    environment_id: str
    title: str | None = None
    status: str
    stop_reason: JsonObject | None = None
    created_at: str
    updated_at: str


class EventIn(BaseModel):
    type: str
    content: list[JsonObject] | JsonObject | None = None


class EventsSendRequest(BaseModel):
    events: list[EventIn]


class EventResponse(BaseModel):
    id: str
    type: str
    session_id: str
    content: JsonObject
    created_at: str
    processed_at: str | None = None


class ApiKeyCreateRequest(BaseModel):
    name: str


class ApiKeyCreateResponse(BaseModel):
    id: str
    name: str
    key: str


def normalize_agent_tool(tool: AgentTool) -> AgentTool:
    if tool.type == "agent_toolset_20260401" and tool.default_config is None:
        tool.default_config = AgentToolDefaultConfig()
    return tool
