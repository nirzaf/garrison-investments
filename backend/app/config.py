from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Construction Internal Portal"
    app_env: str = "development"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    backend_cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    database_url: str = "postgresql+asyncpg://garrison:garrison_dev_password@localhost:5432/garrison_portal"
    redis_url: str = "redis://localhost:6379/0"

    minio_endpoint: str = "localhost:9000"
    minio_root_user: str = "garrison_minio"
    minio_root_password: str = "garrison_minio_password"
    minio_bucket: str = "portal-files"
    minio_secure: bool = False

    backup_encryption_password: str | None = None
    backup_local_dir: str = "/tmp/garrison-backups"
    backup_retention_days: int = 30
    monthly_backup_retention_months: int = 12

    jwt_algorithm: str = "RS256"
    jwt_private_key_path: str | None = None
    jwt_public_key_path: str | None = None
    access_token_expire_minutes: int = 15
    refresh_token_expire_hours: int = 24
    otp_expire_minutes: int = 10
    account_lockout_minutes: int = 30
    auth_failed_attempt_limit: int = 3
    dev_expose_otp: bool = True

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.backend_cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
