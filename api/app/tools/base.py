import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

# Renders a tool's output as Anthropic tool_result content. The UI always gets the
# JSON output; the model can get something richer, e.g. citable search results.
ContentRenderer = Callable[[dict[str, Any]], list[dict[str, Any]]]


@dataclass
class Tool:
    """A tool the model can call. `input_model` is both the JSON schema sent to the
    model and the validator for its arguments (eager input streaming means the API
    does not validate them for us)."""

    name: str
    description: str
    input_model: type[BaseModel]
    handler: Callable[[Any], Awaitable[dict[str, Any]]]
    to_content: ContentRenderer | None = None

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

    def result_content(self, output: dict[str, Any], is_error: bool) -> str | list[dict[str, Any]]:
        if self.to_content and not is_error and "error" not in output:
            return self.to_content(output)
        return json.dumps(output, default=str)
