"""An example agent: a chat model behind an OpenAI-compatible API, with no memory of its own.

Copy this file for your agent and change the address, the body and the paths.
"""

from gateway import gateway

from convy import JsonAgent

agent = JsonAgent(
    gateway,
    body={"model": "gpt-4.1-mini", "messages": "{history}"},
    reply="choices.0.message.content",
    tokens=("usage.prompt_tokens", "usage.completion_tokens"),
)
version = "gpt-4.1-mini"
