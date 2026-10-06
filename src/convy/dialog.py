"""The dialogue: its record, the simulated user who drives it, and the judge who rates it."""

import json

from msgspec import Struct

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

JUDGE_PROMPT = """Below are a dialogue between a user and an agent, and a list of claims about it.
Check every claim strictly against the text of the dialogue.
Answer with JSON only: {{"pass": true or false, "reason": "a short explanation"}}
"pass" is true only if every claim holds. Write the reason in the language of the claims.

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


class Verdict(Struct, frozen=True, tag="verdict"):
    """The judge's decision on an attempt."""

    passed: bool
    reason: str


class NoVerdict(Struct, frozen=True, tag="no_verdict"):
    """There is no verdict, because one of convy's models failed."""

    error: str


class Judge(Struct, frozen=True):
    """A model that decides whether a dialogue meets a scenario's claims."""

    model: Model

    async def verdict(self, transcript: Transcript, claims: tuple[str, ...]) -> Verdict:
        prompt = JUDGE_PROMPT.format(
            dialogue=transcript.as_text(), claims="\n".join(f"- {claim}" for claim in claims)
        )
        return self.parsed(await self.model.reply([{"role": "user", "content": prompt}]))

    def parsed(self, text: str) -> Verdict:
        """The first JSON object with "pass" in the judge's answer, even with text around it.

        An answer without one, or with a "pass" that is not true or false, is a failure of the
        judge's model, like no answer at all."""
        decoder = json.JSONDecoder()
        start = text.find("{")
        while start != -1:
            try:
                found, end = decoder.raw_decode(text, start)
            except json.JSONDecodeError:
                start = text.find("{", start + 1)
                continue
            if isinstance(found, dict) and "pass" in found:
                if type(found["pass"]) is not bool:  # "true" or 1 is not a verdict
                    raise ModelFailure(f'the judge\'s "pass" is not true or false: {text[:200]}')
                return Verdict(found["pass"], str(found.get("reason", "")))
            start = text.find("{", end)  # skip the whole object, nested braces included
        raise ModelFailure(f"the judge did not answer with JSON: {text[:200]}")
