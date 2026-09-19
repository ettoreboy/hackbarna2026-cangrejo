"""Environment-driven settings. Only the keys for the providers you use are required."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Analyzer selection: nebius | gemini | fake. Falls back to any configured provider.
    analyzer_provider: str = Field(default="nebius", alias="ANALYZER_PROVIDER")

    # Gemini (baseline)
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-2.5-flash", alias="GEMINI_MODEL")
    gemini_timeout_seconds: float = Field(default=20.0, alias="GEMINI_TIMEOUT_SECONDS")

    # Nebius Token Factory (primary)
    nebius_api_key: str = Field(default="", alias="NEBIUS_API_KEY")
    nebius_model: str = Field(default="Qwen/Qwen3-235B-A22B-Instruct-2507", alias="NEBIUS_MODEL")
    nebius_base_url: str = Field(default="https://api.tokenfactory.nebius.com/v1/", alias="NEBIUS_BASE_URL")
    nebius_timeout_seconds: float = Field(default=30.0, alias="NEBIUS_TIMEOUT_SECONDS")

    # Author background
    brave_api_key: str = Field(default="", alias="BRAVE_API_KEY")
    search_result_count: int = Field(default=3, alias="SEARCH_RESULT_COUNT")
    wikipedia_lang: str = Field(default="en", alias="WIKIPEDIA_LANG")

    # Speech-to-text for video posts
    slng_api_key: str = Field(default="", alias="SLNG_API_KEY")
    slng_region: str = Field(default="eu-west", alias="SLNG_REGION")
    media_max_seconds: int = Field(default=60, alias="MEDIA_MAX_SECONDS")

    # Server
    host: str = Field(default="127.0.0.1", alias="HOST")
    port: int = Field(default=8000, alias="PORT")
    log_level: str = Field(default="info", alias="LOG_LEVEL")
    cache_ttl_seconds: int = Field(default=86_400, alias="CACHE_TTL_SECONDS")

    @property
    def gemini_configured(self) -> bool:
        return bool(self.gemini_api_key)

    @property
    def nebius_configured(self) -> bool:
        return bool(self.nebius_api_key)

    @property
    def brave_configured(self) -> bool:
        return bool(self.brave_api_key)

    @property
    def slng_configured(self) -> bool:
        return bool(self.slng_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
