import os
import secrets
import warnings
from typing import Annotated, Any, Literal

from pydantic import AnyUrl, BeforeValidator, EmailStr, PostgresDsn, computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing_extensions import Self


def parse_cors(v: Any) -> list[str] | str:
    if isinstance(v, str) and not v.startswith("["):
        return [i.strip() for i in v.split(",") if i.strip()]
    elif isinstance(v, list | str):
        return v
    raise ValueError(v)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.environ.get("ENV_FILE", "../.env.local"),
        env_ignore_empty=True,
        extra="ignore",
    )

    PROJECT_NAME: str = "INUE Scholar"
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str = secrets.token_urlsafe(32)

    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 8
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 30
    FRONTEND_URL: str = "http://localhost:5173"
    ENVIRONMENT: Literal["local", "development", "production"] = "local"

    BACKEND_CORS_ORIGINS: Annotated[list[AnyUrl] | str, BeforeValidator(parse_cors)] = []

    @computed_field
    @property
    def all_cors_origins(self) -> list[str]:
        return [str(origin).rstrip("/") for origin in self.BACKEND_CORS_ORIGINS] + [
            self.FRONTEND_URL
        ]

    POSTGRES_SERVER: str
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str = ""
    POSTGRES_DB: str = ""

    @computed_field
    @property
    def SQLALCHEMY_DATABASE_URI(self) -> str:
        return str(
            PostgresDsn.build(
                scheme="postgresql+asyncpg",
                username=self.POSTGRES_USER,
                password=self.POSTGRES_PASSWORD,
                host=self.POSTGRES_SERVER,
                port=self.POSTGRES_PORT,
                path=self.POSTGRES_DB,
            )
        )

    RESEND_API_KEY: str = ""
    SMTP_TLS: bool = True
    SMTP_SSL: bool = False
    SMTP_PORT: int = 1025
    SMTP_HOST: str = "mailcatcher"
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    EMAILS_FROM_EMAIL: str = "escolar@inue.edu.mx"
    EMAILS_FROM_NAME: str = "INUE Escolar"

    @property
    def use_resend(self) -> bool:
        """Use Resend on prod and Mailcatcher on local."""
        return self.ENVIRONMENT == "production"

    FIRST_SUPERUSER: EmailStr
    FIRST_SUPERUSER_PASSWORD: str

    # Read-only integration API for the calendar system (calendar.inue.online)
    INTEGRATION_API_KEY: str = "changethis"

    # Student/teacher document uploads (mount a volume here in production)
    UPLOADS_DIR: str = "./uploads"

    def _check_default_secret(self, var_name: str, value: str) -> None:
        if value == "changethis":
            message = (
                f'The value of {var_name} is "changethis", '
                "for security, please change it, at least for deployments."
            )
            if self.ENVIRONMENT == "local":
                warnings.warn(message, stacklevel=1)
            else:
                raise ValueError(message)

    @model_validator(mode="after")
    def _enforce_non_default_secrets(self) -> Self:
        self._check_default_secret("SECRET_KEY", self.SECRET_KEY)
        self._check_default_secret("POSTGRES_PASSWORD", self.POSTGRES_PASSWORD)
        self._check_default_secret("FIRST_SUPERUSER_PASSWORD", self.FIRST_SUPERUSER_PASSWORD)
        self._check_default_secret("INTEGRATION_API_KEY", self.INTEGRATION_API_KEY)
        return self


settings = Settings()
