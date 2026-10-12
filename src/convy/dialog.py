"""The dialogue: its record, the simulated user who drives it, and the judge who rates it."""

import json
from typing import Protocol

import msgspec
from msgspec import Struct, field

from convy.agent import Answer, Message, NoThinking, Thinking
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
Lines marked "Agent (thinking)" are what the agent thought; the user did not see them. Judge what
the agent said, unless a claim is about what it thought.
Answer with JSON only: {{"claims": [{{"pass": true or false, "reason": "a short explanation"}}, …]}}
Give one entry per claim, in the order of the list. "pass" is true only if the claim holds.
A claim that ends with "(grades: …)" is graded: instead of "pass", give "grade", exactly one of
those grades. They are listed from worst to best.
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
        """The turn as text, for the judge: the agent's thinking, if the turn has it, on a line
        before what it said."""
        match self.answer.thinking:
            case Thinking(text=text):
                thought = f"Agent (thinking): {text}\n"
            case NoThinking():
                thought = ""
        return f"User: {self.message.text}\n{thought}Agent: {self.answer.text}"


class Transcript(Struct, frozen=True):
    """The record of a dialogue. It never changes: adding a turn gives a new transcript."""

    turns: tuple[Turn, ...] = ()

    def with_turn(self, turn: Turn) -> "Transcript":
        return Transcript((*self.turns, turn))

    def without_thinking(self) -> "Transcript":
        """The same dialogue with only what the agent said."""
        return Transcript(
            tuple(
                msgspec.structs.replace(
                    turn, answer=msgspec.structs.replace(turn.answer, thinking=NoThinking())
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


class Grade(Struct, frozen=True, tag="grade"):
    """The judge's grade of a graded claim: one of the claim's grades, as text."""

    value: str


class NoGrade(Struct, frozen=True, tag="no_grade"):
    """The claim is not graded: it only passes or fails."""


class Reason(Struct, frozen=True, tag="reason"):
    """Why the judge decided as it did."""

    text: str

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("a reason needs text; give NoReason() instead")


class NoReason(Struct, frozen=True, tag="no_reason"):
    """The judge gave no reason."""


class PassDecision(Struct, frozen=True):
    """The judge model's decision on a plain claim, as it writes it."""

    passed: bool = field(name="pass")
    reason: str | None = None


class GradeDecision(Struct, frozen=True):
    """The judge model's decision on a graded claim, as it writes it: a scale's 4 may come as 4."""

    grade: str | int
    reason: str | None = None


class Graded(Struct, frozen=True, forbid_unknown_fields=True):
    """A claim of a scenario graded on its own grades, from worst to best: `pass` is the worst
    grade that still passes. YAML reads a scale such as `[1, 2, 3]` as numbers."""

    text: str = field(name="claim")
    grades: tuple[str | int, ...]
    threshold: str | int = field(name="pass")

    def __post_init__(self) -> None:
        if len(self.grades) < 2:
            raise ValueError(f"{self.text!r}: grades must list at least two grades")
        if len(set(self.levels)) != len(self.levels):
            raise ValueError(f"{self.text!r}: a grade is listed twice")
        if str(self.threshold) not in self.levels:
            raise ValueError(f"{self.text!r}: pass must be one of the grades")

    @property
    def levels(self) -> tuple[str, ...]:
        """The grades as text, from worst to best."""
        return tuple(str(grade) for grade in self.grades)

    def passes(self, grade: str) -> bool:
        """Whether `grade`, one of the claim's grades, is at or above `pass`."""
        return self.levels.index(grade) >= self.levels.index(str(self.threshold))


class Claim(Struct, frozen=True):
    """The judge's decision on one claim of a scenario, and how sure it is. A graded claim also
    has its grade, and passes as the scenario says of that grade."""

    passed: bool = field(name="pass")
    reason: Reason | NoReason = NoReason()
    confidence: Confidence | NoConfidence = NoConfidence()
    grade: Grade | NoGrade = NoGrade()

    def trusted(self, trust: float) -> bool:
        """Whether the decision counts at `trust`: a judge that did not say is trusted."""
        match self.confidence:
            case Confidence(value=value):
                return value >= trust
            case NoConfidence():
                return True


class Verdict(Struct, frozen=True, tag="verdict"):
    """The judge's decision on each claim, in the order of the scenario's claims."""

    claims: tuple[Claim, ...]

    @property
    def passed(self) -> bool:
        """An attempt passes when every claim holds."""
        return all(claim.passed for claim in self.claims)

    def decided(self, trust: float) -> bool:
        """Whether the verdict counts at `trust`: a trusted claim failed, or every claim is
        trusted. One that does not count is cut out of the sample; `passed` still says what the
        judge decided."""
        trusted = [claim for claim in self.claims if claim.trusted(trust)]
        return len(trusted) == len(self.claims) or any(not claim.passed for claim in trusted)


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

    @property
    def reviews_agent_thinking(self) -> bool:
        """Whether the judge reviews the agent's thinking; if not, it gets only what the agent
        said. A judge whose verdicts it changes should change its `name` with it, so `convy
        resume` and `convy compare` see it."""
        ...

    async def decide(
        self, transcript: Transcript, claims: tuple[str | Graded, ...]
    ) -> tuple[Claim, ...]:
        """One decision per claim, in their order, or raise `ModelFailure`. A graded claim gets a
        grade, a plain one none."""
        ...


class ChatJudge(Struct, frozen=True):
    """A chat model that judges: it reads the dialogue and decides each claim, with a reason."""

    model: Model
    reviews_agent_thinking: bool = False

    @property
    def name(self) -> str:
        """The model's name, marked when the judge reviews the agent's thinking."""
        return (
            f"{self.model.name} + agent thinking"
            if self.reviews_agent_thinking
            else self.model.name
        )

    async def decide(
        self, transcript: Transcript, claims: tuple[str | Graded, ...]
    ) -> tuple[Claim, ...]:
        prompt = JUDGE_PROMPT.format(
            dialogue=transcript.as_text(),
            claims="\n".join(
                f"{number}. {self.listed(claim)}" for number, claim in enumerate(claims, 1)
            ),
        )
        answer = await self.model.reply([{"role": "user", "content": prompt}])
        return self.parsed(answer, claims)

    def listed(self, claim: str | Graded) -> str:
        match claim:
            case str():
                return claim
            case Graded(text=text, levels=levels):
                return f"{text} (grades: {', '.join(levels)})"

    def parsed(self, text: str, claims: tuple[str | Graded, ...]) -> tuple[Claim, ...]:
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

    def claims(
        self, items: list[object], claims: tuple[str | Graded, ...], text: str
    ) -> tuple[Claim, ...]:
        """The model's "claims", one per claim, each read into the decision its claim needs."""
        if len(items) != len(claims):
            raise ModelFailure(
                f"the judge decided {len(items)} claims of {len(claims)}: {text[:200]}"
            )
        return tuple(
            self.claim(number, item, claim, text)
            for number, (item, claim) in enumerate(zip(items, claims, strict=True), 1)
        )

    def claim(self, number: int, item: object, claim: str | Graded, text: str) -> Claim:
        """A plain claim needs a "pass" of true or false, a graded one a "grade" of its own;
        "true" or 1 is not a decision. A missing, null or blank "reason" is no reason."""
        try:
            match claim:
                case str():
                    said = msgspec.convert(item, PassDecision)
                    return Claim(said.passed, self.reason(said.reason))
                case Graded(levels=levels):
                    graded = msgspec.convert(item, GradeDecision)
                    grade = str(graded.grade)  # a scale's 4 is "4"
                    if grade not in levels:
                        raise ModelFailure(
                            f"the judge's claim {number}: the grade {grade!r} is not one of "
                            f"{', '.join(levels)}: {text[:200]}"
                        )
                    return Claim(
                        claim.passes(grade), self.reason(graded.reason), grade=Grade(grade)
                    )
        except msgspec.ValidationError as error:
            raise ModelFailure(f"the judge's claim {number}: {error}: {text[:200]}") from None

    def reason(self, said: str | None) -> Reason | NoReason:
        return Reason(said) if said and said.strip() else NoReason()


class Checked(Struct, frozen=True):
    """The same judge, whose answer is checked where it enters: any error of `decide` is
    `ModelFailure`, and so is an answer the run's folder could not hold or that does not give one
    decision per claim. A judge's bug is never blamed on the agent and never stops a run. It
    gives a judge the agent's thinking only if the judge reviews it."""

    judge: Judge

    @property
    def name(self) -> str:
        return self.judge.name

    async def decide(
        self, transcript: Transcript, claims: tuple[str | Graded, ...]
    ) -> tuple[Claim, ...]:
        try:
            seen = (
                transcript if self.judge.reviews_agent_thinking else transcript.without_thinking()
            )
            answer = await self.judge.decide(seen, claims)
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
        for number, (claim, decision) in enumerate(zip(claims, decided, strict=True), 1):
            if error := self.wrong(claim, decision):
                raise ModelFailure(f"{self.name}: claim {number}: {error}")
        return decided

    def wrong(self, claim: str | Graded, decision: Claim) -> str:
        """What is wrong with a decision on a claim, or "": a graded claim needs one of its
        grades and the `pass` the scenario gives it; a plain claim takes no grade."""
        match claim, decision.grade:
            case str(), Grade(value=value):
                return f"a grade, {value!r}, for a claim that is not graded"
            case Graded(), NoGrade():
                return "no grade for a graded claim"
            case Graded(levels=levels), Grade(value=value) if value not in levels:
                return f"the grade {value!r} is not one of {', '.join(levels)}"
            case Graded(), Grade(value=value) if decision.passed != claim.passes(value):
                verdict = "passes" if claim.passes(value) else "fails"
                return f"the grade {value!r} {verdict}, but pass is {decision.passed}"
        return ""
