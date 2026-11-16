from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "Network Analyser API"
    APP_ENV: str = "development"
    # Both spellings of the Vite dev origin: a browser treats `localhost` and
    # `127.0.0.1` as DIFFERENT origins, so both must be allowed.
    CORS_ORIGINS: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
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
    PING_INTERVAL_SECONDS: float = 8.0
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
    # The default below is a placeholder, not a secret. The backend refuses to
    # start on it, or on anything shorter than 32 characters, unless DEMO_MODE
    # is on (see app.core.security.require_private_jwt_secret).
    JWT_SECRET_KEY: str = "CHANGE_ME_DEV_ONLY_INSECURE_DEFAULT"
    JWT_ALGORITHM: str = "HS256"
    # How long a login lasts. There are no refresh tokens: after this the user
    # logs in again.
    JWT_EXPIRE_MINUTES: int = 60

    # Initial credentials (app/db/seed_users.py, docs/security.md).
    # Passwords the two seeded accounts get when the database is first
    # created. Unset (or empty): a random one is generated and written to the
    # log once. Either way the account must change it at first login.
    ADMIN_INITIAL_PASSWORD: str | None = None
    VIEWER_INITIAL_PASSWORD: str | None = None
    # INSECURE, for demos only. True seeds the documented demo credentials
    # (admin / admin123, viewer / viewer123) and switches the forced password
    # change off. Never set it on a network you care about.
    DEMO_MODE: bool = False

    @field_validator("CORS_ORIGINS")
    @classmethod
    def _exact_origins_only(cls, origins: list[str]) -> list[str]:
        """CORS is strict: every allowed origin is spelled out. No wildcard,
        and an origin is scheme://host[:port] with nothing after it."""
        for origin in origins:
            rest = origin.removeprefix("https://").removeprefix("http://")
            if rest == origin or not rest or any(char in rest for char in "*/ "):
                raise ValueError(
                    f"CORS_ORIGINS entry {origin!r} is not an exact origin such as http://localhost:8411"
                )
        return origins


settings = Settings()