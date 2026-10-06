"""The models that play the user and judge the dialogue."""

from gateway import gateway

from convy import Models, OpenAiModel

models = Models(
    user=OpenAiModel(gateway, "gpt-4.1-mini"),
    judge=OpenAiModel(gateway, "gpt-4.1-mini"),
)
