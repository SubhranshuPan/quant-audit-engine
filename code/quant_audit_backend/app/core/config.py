"""Application settings, overridable from the environment or a .env file."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="QUANT_", extra="ignore")

    project_name: str = "Quant AI Investment Strategy Audit Engine"
    version: str = "1.0.0"
    api_v1_prefix: str = "/api/v1"

    # Wide open by default because this ships as a local analyst tool; narrow it
    # to the real dashboard origin before exposing the service to a network.
    cors_origins: list[str] = ["*"]

    # Guardrails on user input: yfinance calls are slow and unbounded requests
    # are the easiest way to hang a worker.
    max_tickers: int = 50
    max_upload_bytes: int = 10 * 1024 * 1024
    min_observations: int = 30  # below this the HAC standard error is not trustworthy

    # Public deployments only. One cheap request triggers an outbound market-data
    # download, so an unauthenticated caller is otherwise a free amplifier.
    rate_limit_per_minute: int = 30

    # yfinance is frequently blocked or throttled from datacenter IPs. Prices are
    # cached so repeat requests cost nothing upstream, and a bundled snapshot keeps
    # a public demo working when live data is unavailable. Snapshot responses are
    # always labelled as such -- an audit must never present frozen data as live.
    price_cache_seconds: int = 3600
    use_snapshot_fallback: bool = True


settings = Settings()
