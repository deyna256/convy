"""The models convy itself uses: the simulated user's and the judge's."""

from typing import TYPE_CHECKING, Protocol

from msgspec import Struct

from convy.http import HttpFailure, JsonEndpoint, JsonPath

if TYPE_CHECKING:  # dialog.py imports this module
    from convy.dialog import Judge


class ModelFailure(Exception):
    """One of convy's models failed, not the agent."""


class Model(Protocol):
    """A chat model. `messages` use the OpenAI Chat Completions format."""

    @property
    def name(self) -> str:
        """The model's name, written to journals instead of the model itself."""
        ...

    async def reply(self, messages: list[dict[str, str]]) -> str:
        """Reply to the messages, or raise `ModelFailure`."""
        ...


class OpenAiModel(Struct, frozen=True):
    """A model behind an OpenAI Chat Completions API; `endpoint` points to `…/chat/completions`."""

    endpoint: JsonEndpoint
    name: str

    async def reply(self, messages: list[dict[str, str]]) -> str:
        try:
            data = await self.endpoint.post({"model": self.name, "messages": messages})
            text = JsonPath("choices.0.message.content").find(data)
        except (HttpFailure, LookupError) as failure:
            raise ModelFailure(f"{self.name}: {failure}") from failure
        if not isinstance(text, str):
            raise ModelFailure(f"{self.name}: expected text, got {text!r:.100}")
        try:
            text.encode()  # a lone surrogate, half an emoji, would break the journal
        except UnicodeEncodeError:
            raise ModelFailure(f"{self.name}: the reply is not valid Unicode") from None
        return text


class Contained(Struct, frozen=True):
    """The same model, whose own bugs are its failures too: any error of `reply` is `ModelFailure`,
    so a model's bug is never blamed on the agent and never stops a run."""

    model: Model

    @property
    def name(self) -> str:
        return self.model.name

    async def reply(self, messages: list[dict[str, str]]) -> str:
        try:
            return await self.model.reply(messages)
        except ModelFailure:
            raise
        except Exception as error:  # a model is user code too: any bug is a failed model
            raise ModelFailure(f"{self.name}: {type(error).__name__}: {error}") from error


class Models(Struct, frozen=True):
    """The model that plays the user, and the judge."""

    user: Model
    judge: "Judge"
