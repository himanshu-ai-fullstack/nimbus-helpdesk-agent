from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError


@dataclass
class Tool:
    """A tool the model can call. `input_model` is both the JSON schema sent to the
    model and the validator for its arguments (eager input streaming means the API
    does not validate them for us)."""

    name: str
    description: str
    input_model: type[BaseModel]
    handler: Callable[[Any], Awaitable[dict[str, Any]]]

    def to_anthropic(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_model.model_json_schema(),
            "eager_input_streaming": True,
        }

    async def run(self, raw_input: Any) -> tuple[dict[str, Any], bool]:
        """Returns (output, is_error)."""
        try:
            args = self.input_model.model_validate(raw_input)
        except ValidationError as e:
            return {"error": "invalid input", "details": e.errors(include_url=False)}, True
        try:
            return await self.handler(args), False
        except Exception as e:  # noqa: BLE001 - surfaced to the model so it can recover
            return {"error": str(e)}, True
