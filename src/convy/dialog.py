"""The dialogue: its record, the simulated user who drives it, and the judge who rates it."""

import json
from typing import Protocol

import msgspec
from msgspec import Struct, field

from convy.agent import Answer, Message
from convy.model import Model, ModelFailure

STOP = "###STOP###"

OPENING = "(The assistant is waiting for your first message.)"

USER_PROMPT = """You are playing a user who writes to an assistant. Follow the instructions below.

Rules:
- Write one message at a time, as a real person does in a chat.
- Do not give away the whole of the instructions at once: say only what the current step needs.
- Do not make up facts that are not in the instructions. If you are asked about something they do
  not cover, say that you do not know.
- Keep to the persona from the instructions until the end of the conversation.
- Write in the language of the instructions.
- When the goal is reached, or it is clear that it cannot be reached, answer exactly {stop}

Instructions:
{instructions}"""

JUDGE_PROMPT = """Below are a dialogue between a user and an agent, and a numbered list of claims
about it. Check every claim strictly against the text of the dialogue.
Answer with JSON only: {{"claims": [{{"pass": true or false, "reason": "a short explanation"}}, …]}}
Give one entry per claim, in the order of the list. "pass" is true only if the claim holds.
Write the reasons in the language of the claims.

Dialogue:
{dialogue}

Claims:
{claims}"""


class Turn(Struct, frozen=True):
    """A message, the agent's answer, and how many seconds the answer took."""

    message: Message
    answer: Answer
    seconds: float


class Transcript(Struct, frozen=True):
    """The record of a dialogue. It never changes: adding a turn gives a new transcript."""

    turns: tuple[Turn, ...] = ()

    def with_turn(self, turn: Turn) -> "Transcript":
        return Transcript((*self.turns, turn))

    def as_text(self) -> str:
        """The dialogue as text, for the judge."""
        return "\n".join(f"User: {t.message.text}\nAgent: {t.answer.text}" for t in self.turns)

    def as_chat(self) -> list[dict[str, str]]:
        """The dialogue for the simulated user: its messages are `assistant`, the agent's `user`."""
        chat = []
        for turn in self.turns:
            chat.append({"role": "assistant", "content": turn.message.text})
            chat.append({"role": "user", "content": turn.answer.text})
        return chat


class Finished(Struct, frozen=True):
    """The simulated user has nothing more to say."""


class SimulatedUser(Struct, frozen=True):
    """A model that plays a person following a scenario's instructions."""

    model: Model
    instructions: str

    async def next(self, transcript: Transcript) -> Message | Finished:
        system = USER_PROMPT.format(stop=STOP, instructions=self.instructions)
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": OPENING},
            *transcript.as_chat(),
        ]
        text = (await self.model.reply(messages)).strip()
        if STOP in text:
            return Finished()
        if not text:
            raise ModelFailure("the simulated user gave an empty message")
        return Message(text)


class Claim(Struct, frozen=True):
    """The judge's decision on one claim of a scenario."""

    passed: bool = field(name="pass")
    reason: str


class Verdict(Struct, frozen=True, tag="verdict"):
    """The judge's decision on each claim, in the order of the scenario's claims."""

    claims: tuple[Claim, ...]

    @property
    def passed(self) -> bool:
        """An attempt passes when every claim holds."""
        return all(claim.passed for claim in self.claims)


class Failed(Struct, frozen=True, tag="failed"):
    """The agent failed: the judge was not asked, and the attempt did not pass."""

    reason: str


class NoVerdict(Struct, frozen=True, tag="no_verdict"):
    """There is no verdict, because one of convy's models failed."""

    error: str


class Judge(Protocol):
    """Anything that decides whether a dialogue meets each of a scenario's claims."""

    @property
    def name(self) -> str:
        """The judge's name, written to the run instead of the judge itself."""
        ...

    async def decide(self, transcript: Transcript, claims: tuple[str, ...]) -> tuple[Claim, ...]:
        """One decision per claim, in their order, or raise `ModelFailure`."""
        ...


class ChatJudge(Struct, frozen=True):
    """A chat model that judges: it reads the dialogue and decides each claim, with a reason."""

    model: Model

    @property
    def name(self) -> str:
        return self.model.name

    async def decide(self, transcript: Transcript, claims: tuple[str, ...]) -> tuple[Claim, ...]:
        prompt = JUDGE_PROMPT.format(
            dialogue=transcript.as_text(),
            claims="\n".join(f"{number}. {claim}" for number, claim in enumerate(claims, 1)),
        )
        answer = await self.model.reply([{"role": "user", "content": prompt}])
        return self.parsed(answer, len(claims))

    def parsed(self, text: str, count: int) -> tuple[Claim, ...]:
        """The first JSON object with "claims" in the model's answer, even with text around it.

        An answer without one, or with claims convy cannot use, is a failure of the judge's model,
        like no answer at all."""
        decoder = json.JSONDecoder()
        start = text.find("{")
        while start != -1:
            try:
                found, end = decoder.raw_decode(text, start)
            except json.JSONDecodeError:
                start = text.find("{", start + 1)
                continue
            if isinstance(found, dict) and "claims" in found:
                return self.claims(found["claims"], count, text)
            start = text.find("{", end)  # skip the whole object, nested braces included
        raise ModelFailure(f"the judge did not answer with JSON: {text[:200]}")

    def claims(self, found: object, count: int, text: str) -> tuple[Claim, ...]:
        """The model's "claims", checked: one object per claim, each with a "pass" of true or
        false; "true" or 1 is not a decision."""
        if not isinstance(found, list) or not all(isinstance(item, dict) for item in found):
            raise ModelFailure(f'the judge\'s "claims" is not a list of objects: {text[:200]}')
        if len(found) != count:
            raise ModelFailure(f"the judge decided {len(found)} claims of {count}: {text[:200]}")
        if any(type(item.get("pass")) is not bool for item in found):
            raise ModelFailure(f'the judge\'s "pass" is not true or false: {text[:200]}')
        return tuple(Claim(item["pass"], str(item.get("reason", ""))) for item in found)


class Checked(Struct, frozen=True):
    """The same judge, whose answer is checked where it enters: any error of `decide` is
    `ModelFailure`, and so is an answer the run's folder could not hold or that does not give one
    decision per claim. A judge's bug is never blamed on the agent and never stops a run."""

    judge: Judge

    @property
    def name(self) -> str:
        return self.judge.name

    async def decide(self, transcript: Transcript, claims: tuple[str, ...]) -> tuple[Claim, ...]:
        try:
            answer = await self.judge.decide(transcript, claims)
        except ModelFailure:
            raise
        except Exception as error:  # a judge is user code: any bug is a failed model
            raise ModelFailure(f"{self.name}: {type(error).__name__}: {error}") from error
        try:  # written and read back as the run's folder does
            decided = msgspec.json.decode(msgspec.json.encode(answer), type=tuple[Claim, ...])
        except (
            msgspec.ValidationError,
            msgspec.EncodeError,
            TypeError,
            UnicodeEncodeError,
        ) as error:
            raise ModelFailure(f"{self.name}: the decisions are not claims: {error}") from error
        if len(decided) != len(claims):
            raise ModelFailure(f"{self.name}: decided {len(decided)} claims of {len(claims)}")
        return decided
