"""The models that play the user and judge the dialogue."""

from convy import Models, OpenAiModel

from gateway import MODEL, gateway

models = Models(user=OpenAiModel(gateway, MODEL), judge=OpenAiModel(gateway, MODEL))
