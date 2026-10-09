"""The models that play the user and judge the dialogue."""

from convy import ChatJudge, Models, OpenAiModel

from gateway import gateway

models = Models(
    user=OpenAiModel(gateway, "gpt-4.1-mini"),
    judge=ChatJudge(OpenAiModel(gateway, "gpt-4.1-mini")),
)
