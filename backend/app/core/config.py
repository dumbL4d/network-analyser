from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "Network Analyser API"
    APP_ENV: str = "development"
    CORS_ORIGINS: list[str] = ["http://localhost:5173"]
    DATABASE_PATH: str = "./data/network_analyser.db"
    # Optional absolute/relative path to the devices seed JSON. When unset,
    # main.py falls back to the repo-root layout (local dev) or ./infra next to
    # the working directory (Docker image). Making it configurable lets a
    # deployed container point at a mounted read-only copy of the seed file.
    SEED_PATH: str | None = None

    # Ping engine
    # True -> raw ICMP sockets (needs root / CAP_NET_RAW).
    # False -> unprivileged fallback mode (no root required).
    PING_PRIVILEGED: bool = True
    PING_TIMEOUT_SECONDS: float = 2.0
    PING_INTERVAL_SECONDS: float = 10.0
    LATENCY_WARN_MS: float = 100.0
    LATENCY_CRIT_MS: float = 500.0
    # False -> the app starts without the background poll loop. The test suite
    # sets this; nothing is pinged, so devices stay "unknown".
    POLL_ENABLED: bool = True

    # Rolling history: how many recent samples per device are kept in memory
    # (the hot cache behind the default /api/history response).
    HISTORY_MAX_SAMPLES: int = 36

    # Persistence and retention (app/services/retention.py)
    # Raw samples older than this are folded into 1-minute rollups.
    RAW_RETENTION_HOURS: float = 24.0
    # 1-minute rollups older than this are deleted.
    ROLLUP_RETENTION_DAYS: float = 30.0
    # Status transitions older than this are deleted. It is also the window
    # over which /api/flaps counts flaps.
    TRANSITION_RETENTION_DAYS: float = 30.0
    # How often the retention job runs.
    RETENTION_INTERVAL_SECONDS: float = 3600.0

    # Fault injection (app/services/chaos.py, docs/chaos.md). Both must be set
    # for the chaos endpoints to do anything; otherwise they answer 503.
    # Where the chaos agent listens, e.g. http://chaos-agent:8081.
    CHAOS_AGENT_URL: str | None = None
    # The shared secret the agent expects in every request.
    CHAOS_AGENT_TOKEN: str | None = None

    # JWT auth
    # WARNING: the insecure default below MUST be overridden via env var in any
    # real deployment. It exists ONLY for local development convenience.
    JWT_SECRET_KEY: str = "CHANGE_ME_DEV_ONLY_INSECURE_DEFAULT"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 480  # 8h, matching the original tool's session TTL


settings = Settings()