"""The dialogue: its record, the simulated user who drives it, and the judge who rates it."""

import json
from typing import Protocol

import msgspec
from msgspec import Struct, field

from convy.agent import Answer, Message
from convy.busy import Places
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

    def as_text(self) -> str:
        """The turn as text, for the judge: only what was said."""
        return f"User: {self.message.text}\nAgent: {self.answer.text}"


class Transcript(Struct, frozen=True):
    """The record of a dialogue. It never changes: adding a turn gives a new transcript."""

    turns: tuple[Turn, ...] = ()

    def with_turn(self, turn: Turn) -> "Transcript":
        return Transcript((*self.turns, turn))

    def without_steps(self) -> "Transcript":
        """The same dialogue with only what was said, without the steps of the answers."""
        return Transcript(
            tuple(
                msgspec.structs.replace(
                    turn,
                    answer=msgspec.structs.replace(turn.answer, steps=(), steps_complete=False),
                )
                for turn in self.turns
            )
        )

    def as_text(self) -> str:
        """The dialogue as text, for the judge, turn by turn."""
        return "\n".join(turn.as_text() for turn in self.turns)

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


class Confidence(Struct, frozen=True, tag="confidence"):
    """How sure the judge is of its decision on a claim: from 0 to 1."""

    value: float

    def __post_init__(self) -> None:
        if not 0 <= self.value <= 1:  # NaN fails too
            raise ValueError(f"confidence must be from 0 to 1, got {self.value}")


class NoConfidence(Struct, frozen=True, tag="no_confidence"):
    """The judge did not say how sure it is."""


class Reason(Struct, frozen=True, tag="reason"):
    """Why the judge decided as it did."""

    text: str

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("a reason needs text; give NoReason() instead")


class NoReason(Struct, frozen=True, tag="no_reason"):
    """The judge gave no reason."""


class PassDecision(Struct, frozen=True, forbid_unknown_fields=True):
    """The judge model's decision on a plain claim, as it writes it."""

    passed: bool = field(name="pass")
    reason: str | None = None


class Claim(Struct, frozen=True, forbid_unknown_fields=True):
    """The judge's decision on one claim of a scenario, and how sure it is."""

    passed: bool = field(name="pass")
    reason: Reason | NoReason = NoReason()
    confidence: Confidence | NoConfidence = NoConfidence()

    def trusted(self, trust: float) -> bool:
        """Whether confidence meets `trust`: a judge that did not say is trusted."""
        match self.confidence:
            case Confidence(value=value):
                return value >= trust
            case NoConfidence():
                return True

    def holds(self, trust: float) -> bool:
        """A positive decision holds only when its confidence meets the run's trust."""
        return self.passed and self.trusted(trust)


class Verdict(Struct, frozen=True, tag="verdict"):
    """The judge's decision on each claim, in the order of the scenario's claims."""

    claims: tuple[Claim, ...]


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
        """The judge's name, written to the run instead of the judge itself. A judge whose verdicts
        a setting changes should change its `name` with it, so `convy resume` and `convy compare`
        see it."""
        ...

    async def decide(self, transcript: Transcript, claims: tuple[str, ...]) -> tuple[Claim, ...]:
        """One decision per claim, in their order, or raise `ModelFailure`."""
        ...


class ChatJudge(Struct, frozen=True):
    """A chat model that judges: it reads the dialogue and decides each claim, with a reason."""

    model: Model

    @property
    def name(self) -> str:
        """The model's name."""
        return self.model.name

    async def decide(self, transcript: Transcript, claims: tuple[str, ...]) -> tuple[Claim, ...]:
        prompt = JUDGE_PROMPT.format(
            dialogue=transcript.as_text(),
            claims="\n".join(f"{number}. {claim}" for number, claim in enumerate(claims, 1)),
        )
        answer = await self.model.reply([{"role": "user", "content": prompt}])
        return self.parsed(answer, claims)

    def parsed(self, text: str, claims: tuple[str, ...]) -> tuple[Claim, ...]:
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
            match found:
                case {"claims": list() as items}:
                    return self.claims(items, claims, text)
                case {"claims": _}:
                    raise ModelFailure(f'the judge\'s "claims" is not a list: {text[:200]}')
            start = text.find("{", end)  # skip the whole object, nested braces included
        raise ModelFailure(f"the judge did not answer with JSON: {text[:200]}")

    def claims(self, items: list[object], claims: tuple[str, ...], text: str) -> tuple[Claim, ...]:
        """The model's "claims", one per claim, each read into the decision its claim needs."""
        if len(items) != len(claims):
            raise ModelFailure(
                f"the judge decided {len(items)} claims of {len(claims)}: {text[:200]}"
            )
        return tuple(self.claim(number, item, text) for number, item in enumerate(items, 1))

    def claim(self, number: int, item: object, text: str) -> Claim:
        """A claim needs a boolean pass; a missing, null or blank reason is no reason."""
        try:
            said = msgspec.convert(item, PassDecision)
            return Claim(said.passed, self.reason(said.reason))
        except msgspec.ValidationError as error:
            raise ModelFailure(f"the judge's claim {number}: {error}: {text[:200]}") from None

    def reason(self, said: str | None) -> Reason | NoReason:
        return Reason(said) if said and said.strip() else NoReason()


class PatientJudge(Struct, frozen=True):
    """The same judge, each decision sent in a place of `places`, which waits for a busy service."""

    judge: Judge
    places: Places

    @property
    def name(self) -> str:
        return self.judge.name

    async def decide(self, transcript: Transcript, claims: tuple[str, ...]) -> tuple[Claim, ...]:
        return await self.places.call(lambda: self.judge.decide(transcript, claims))


class Checked(Struct, frozen=True):
    """The same judge, whose answer is checked where it enters: any error of `decide` is
    `ModelFailure`, and so is an answer the run's folder could not hold or that does not give one
    decision per claim. A judge's bug is never blamed on the agent and never stops a run. A judge
    gets only what was said."""

    judge: Judge

    @property
    def name(self) -> str:
        return self.judge.name

    async def decide(self, transcript: Transcript, claims: tuple[str, ...]) -> tuple[Claim, ...]:
        try:
            answer = await self.judge.decide(transcript.without_steps(), claims)
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
