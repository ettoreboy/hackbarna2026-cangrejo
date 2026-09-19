"""Environment-driven settings. Only the keys for the providers you use are required."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Analyzer selection: nebius | gemini | fake. Falls back to any configured provider.
    analyzer_provider: str = Field(default="nebius", alias="ANALYZER_PROVIDER")

    # Nebius Token Factory (primary). gpt-oss-120b at low reasoning effort measured 3.7 s on
    # the benchmark post with strict json_schema; Qwen3-235B took 9-16 s, Qwen3-30B-A3B 27 s.
    nebius_api_key: str = Field(default="", alias="NEBIUS_API_KEY")
    nebius_model: str = Field(default="openai/gpt-oss-120b", alias="NEBIUS_MODEL")
    nebius_fast_model: str = Field(default="", alias="NEBIUS_FAST_MODEL", description="Step-1 model; empty = NEBIUS_MODEL")
    nebius_reasoning_effort: str = Field(default="low", alias="NEBIUS_REASONING_EFFORT", description="low|medium|high|'' to omit")
    nebius_base_url: str = Field(default="https://api.tokenfactory.nebius.com/v1/", alias="NEBIUS_BASE_URL")
    nebius_timeout_seconds: float = Field(default=30.0, alias="NEBIUS_TIMEOUT_SECONDS")
    # Verdicts proved unstable run to run at 0.2 (only 72% of 50 tweets agreed across two
    # identical runs). 0 is the default so the same post gives the same answer.
    nebius_temperature: float = Field(default=0.0, alias="NEBIUS_TEMPERATURE")

    # Gemini (baseline)
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-2.5-flash", alias="GEMINI_MODEL")
    gemini_timeout_seconds: float = Field(default=20.0, alias="GEMINI_TIMEOUT_SECONDS")
    # Same reason as nebius_temperature: a comparison run must measure the prompt or the
    # provider, not sampling noise. Both arms sit at 0 by default.
    gemini_temperature: float = Field(default=0.0, alias="GEMINI_TEMPERATURE")

    # Evidence and author background. Brave is prepaid ($5 per 1 000 requests): every result
    # is cached on disk and live calls stop at BRAVE_BUDGET.
    brave_api_key: str = Field(default="", alias="BRAVE_API_KEY")
    brave_budget: int = Field(default=1_500, alias="BRAVE_BUDGET", description="max live Brave calls, counted in the cache db")
    background_brave_fallback: bool = Field(default=False, alias="BACKGROUND_BRAVE_FALLBACK", description="use Brave for unknown authors")
    search_cache_path: str = Field(default=".cache/brave.sqlite", alias="SEARCH_CACHE_PATH", description="empty = in-memory")
    evidence_result_count: int = Field(default=5, alias="EVIDENCE_RESULT_COUNT")
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
