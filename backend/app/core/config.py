from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "Network Analyser API"
    APP_ENV: str = "development"
    CORS_ORIGINS: list[str] = ["http://localhost:5173"]
    DATABASE_PATH: str = "./data/network_analyser.db"

    # Ping engine
    # True -> raw ICMP sockets (needs root / CAP_NET_RAW).
    # False -> unprivileged fallback mode (no root required).
    PING_PRIVILEGED: bool = True
    PING_TIMEOUT_SECONDS: float = 2.0
    PING_INTERVAL_SECONDS: float = 10.0
    LATENCY_WARN_MS: float = 100.0
    LATENCY_CRIT_MS: float = 500.0

    # Rolling history
    HISTORY_MAX_SAMPLES: int = 36

    # JWT auth
    # WARNING: the insecure default below MUST be overridden via env var in any
    # real deployment. It exists ONLY for local development convenience.
    JWT_SECRET_KEY: str = "CHANGE_ME_DEV_ONLY_INSECURE_DEFAULT"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 480  # 8h, matching the original tool's session TTL


settings = Settings()