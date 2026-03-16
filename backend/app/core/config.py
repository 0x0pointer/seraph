import logging
import warnings

from pydantic_settings import BaseSettings, SettingsConfigDict

_logger = logging.getLogger(__name__)

_WEAK_SECRETS = {
    "changeme-super-secret-key-at-least-32-chars",
    "secret",
    "changeme",
    "your-secret-key",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str = "postgresql+asyncpg://seraph:seraph@localhost:5432/seraph"

    # JWT
    secret_key: str = "changeme-super-secret-key-at-least-32-chars"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    # CORS
    cors_origins: list[str] = ["http://localhost:3000"]

    # Cloudflare Turnstile (use test keys by default)
    turnstile_secret_key: str = "1x0000000000000000000000000000000AA"

    # App
    app_name: str = "Seraph"
    debug: bool = False

    # Frontend base URL (used in reset-password email links)
    frontend_url: str = "http://localhost:3000"

    # SMTP — leave smtp_host empty to disable email sending
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "noreply@seraph.io"
    smtp_tls: bool = True   # use STARTTLS; set False for plain / SSL-on-connect

    # Seed admin password — required in production (debug=False)
    admin_password: str = ""


settings = Settings()

if settings.secret_key in _WEAK_SECRETS or len(settings.secret_key) < 32:
    if settings.debug:
        warnings.warn(
            "SECRET_KEY is weak or using the default placeholder. "
            "Set a strong random value in your .env (e.g. openssl rand -hex 32).",
            stacklevel=1,
        )
    else:
        raise RuntimeError(
            "Refusing to start: SECRET_KEY is weak or using the default placeholder. "
            "Generate one with: openssl rand -hex 32"
        )
