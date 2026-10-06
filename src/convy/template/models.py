"""The models that play the user and judge the dialogue."""

from convy import Models, OpenAiModel

from gateway import gateway

models = Models(
    user=OpenAiModel(gateway, "gpt-4.1-mini"),
    judge=OpenAiModel(gateway, "gpt-4.1-mini"),
)
