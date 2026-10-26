"""Tenant configuration, loaded from `tenants/<slug>/tenant.yaml`.

Config is code: prompts and policies are reviewed in git, validated here at
startup, and versioned by a content hash that is stored on every conversation."""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SLUG = re.compile(r"^[a-z][a-z0-9-]{1,30}$")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ActionPolicy(_Strict):
    """Rules the backend enforces before the agent may propose an action. The model
    can only ever create a *pending* action; a person approves it."""

    label: str = Field(description="Shown on cards and to the model, e.g. 'Refund'")
    description: str = Field(description="When the agent should propose it")
    record_type: str
    require_status: list[str] = []
    window_days: int | None = Field(default=None, ge=1)
    amount: Literal["required", "none"] = "required"
    max_amount_usd: float | None = Field(default=None, gt=0)
    # Pending and approved actions on the same record count against its amount.
    cap_to_remaining: bool = False

    @model_validator(mode="after")
    def _amount_rules(self) -> "ActionPolicy":
        if self.amount == "none" and (self.max_amount_usd or self.cap_to_remaining):
            raise ValueError("max_amount_usd and cap_to_remaining need amount: required")
        return self


class Triage(_Strict):
    categories: list[str] = Field(min_length=2)
    priority_guide: str


class Display(_Strict):
    account_label: str = "Customer"
    # attribute key -> label, shown on the account card in this order
    account_fields: dict[str, str] = {}
    # record type -> label, e.g. {"invoice": "Invoice"}
    record_labels: dict[str, str] = {}


class Models(_Strict):
    chat: str = "claude-opus-5-5"
    # Cheaper model for triage and other structured side tasks
    fast: str = "claude-haiku-5-5"
    chat_effort: Literal["low", "medium", "high"] = "medium"


class TenantConfig(_Strict):
    slug: str
    name: str
    industry: str = Field(description="One phrase, e.g. 'project management SaaS'")
    tagline: str
    brand_color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    persona: str = Field(description="The agent's name, e.g. 'Nim'")
    audience: Literal["customers", "employees"] = "customers"
    greeting: str
    prompt: str = Field(description="Company-specific guidance, added to the shared rules")
    suggestions: list[str] = Field(min_length=1, max_length=6)
    actions: dict[str, ActionPolicy] = {}
    triage: Triage
    display: Display = Display()
    models: Models = Models()
    version: str = Field(default="", description="Set by the loader from the file hash")

    @field_validator("slug")
    @classmethod
    def _slug(cls, v: str) -> str:
        if not SLUG.match(v):
            raise ValueError("slug must be lowercase letters, digits and dashes")
        return v

    @field_validator("actions")
    @classmethod
    def _action_keys(cls, v: dict[str, ActionPolicy]) -> dict[str, ActionPolicy]:
        for key in v:
            if not re.match(r"^[a-z][a-z0-9_]*$", key):
                raise ValueError(f"action kind {key!r} must be snake_case")
        return v

    def public(self) -> dict:
        """What the web app may see: branding and copy, never prompts or policies'
        internals beyond their labels."""
        return {
            "slug": self.slug,
            "name": self.name,
            "industry": self.industry,
            "tagline": self.tagline,
            "brand_color": self.brand_color,
            "persona": self.persona,
            "audience": self.audience,
            "greeting": self.greeting,
            "suggestions": self.suggestions,
            "actions": {k: a.label for k, a in self.actions.items()},
            "display": self.display.model_dump(),
        }
