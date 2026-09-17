from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "Network Analyser API"
    APP_ENV: str = "development"
    CORS_ORIGINS: list[str] = ["http://localhost:5173"]
    DATABASE_PATH: str = "./data/network_analyser.db"


settings = Settings()