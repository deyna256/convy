"""The model gateway, shared by models.py and the agents. Keys come from .env."""

from pydantic import HttpUrl, SecretStr
from pydantic_settings import SettingsConfigDict

from convy import Env, JsonEndpoint


class GatewayEnv(Env):
    model_config = SettingsConfigDict(env_prefix="GW_")
    base_url: HttpUrl  # GW_BASE_URL
    api_key: SecretStr  # GW_API_KEY


gw = GatewayEnv()
gateway = JsonEndpoint(
    f"{str(gw.base_url).rstrip('/')}/chat/completions",
    headers={"Authorization": f"Bearer {gw.api_key.get_secret_value()}"},
)
