from functools import lru_cache
from typing import Literal
from uuid import UUID

from pydantic import EmailStr, Field, HttpUrl, IPvAnyAddress, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.business_policy import DEFAULT_BUSINESS_CURRENCY, BusinessPolicy, BusinessPolicyResponse
from app.utils.secret_files import read_private_secret_file


class Settings(BaseSettings, BusinessPolicy):
    app_name: str = "Construction Internal Portal"
    app_env: str = "development"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    backend_cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    frontend_base_url: str | None = None
    super_admin_enabled: bool = False
    super_admin_otp_key: SecretStr | None = None
    support_portal_enabled: bool = False
    support_custody_mode: Literal["paired", "single_owner"] = "paired"
    support_ingress_peer: IPvAnyAddress | None = None
    support_recovery_key: SecretStr | None = None
    support_recovery_delivery_enabled: bool = False
    support_recovery_allowed_origins: str = ""
    support_email_otp_key: SecretStr | None = None
    support_email_otp_only_login: bool = False
    support_email_otp_recipients: dict[UUID, EmailStr] = Field(default_factory=dict, repr=False)

    database_url: str = (
        "postgresql+asyncpg://garrison:garrison_dev_password@localhost:5432/garrison_portal"
    )
    redis_url: str = "redis://localhost:6379/0"
    auth_rate_limit_window_seconds: int = 60
    auth_rate_limit_max_requests: int = 10
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = False
    smtp_from_email: str = "no-reply@garrisons.lk"
    smtp_from_name: str = "Garrisons Investments"
    usesend_api_url: HttpUrl | None = None
    usesend_api_key: SecretStr | None = None
    cloudflare_email_account_id: str | None = None
    cloudflare_email_api_token: SecretStr | None = None
    cloudflare_email_from: str | None = None
    exception_email_recipients: str = "admin@garrisons.lk"
    exception_email_enabled: bool | None = None
    hr_encryption_key: SecretStr | None = None
    hr_reminder_window_days: int | None = Field(default=None, ge=1, le=365)
    hr_service_request_sla_days: int | None = Field(default=None, ge=1, le=365)
    hr_probation_review_reminder_days: int | None = Field(default=None, ge=1, le=365)
    hr_scheduled_leave_policy_ids: list[UUID] = Field(default_factory=list, max_length=100)
    hr_line_manager_review_enabled: bool = False
    hr_self_time_submission_enabled: bool = False
    notification_retention_days: int = 90

    minio_endpoint: str = "localhost:9000"
    minio_root_user: str = "garrison_minio"
    minio_root_password: str = "garrison_minio_password"
    minio_bucket: str = "portal-files"
    minio_secure: bool = False
    minio_public_endpoint: str | None = None
    minio_public_secure: bool | None = None

    report_email_recipients: str = "admin@garrisons.lk"
    report_pdf_template_name: str = "company-standard"

    backup_encryption_password: str | None = Field(default=None, repr=False)
    backup_encryption_password_file: str | None = Field(default=None, repr=False)
    import_outbox_encryption_key: SecretStr | None = None
    import_outbox_previous_encryption_keys: SecretStr | None = None
    backup_local_dir: str = "/tmp/garrison-backups"
    backup_retention_days: int = 30
    monthly_backup_retention_months: int = 12
    log_source_service: str = "backend-api"
    log_instance_id: str | None = None
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_healthchecks: bool = False
    log_hot_retention_days: int = 30
    log_archive_retention_days: int = 365
    log_purge_enabled: bool = False
    audit_retention_policy_path: str | None = None
    audit_retention_policy_sha256: str | None = None
    log_stream_poll_seconds: float = 1.0

    jwt_algorithm: str = "RS256"
    jwt_private_key_path: str | None = None
    jwt_public_key_path: str | None = None
    access_token_expire_minutes: int = 15
    refresh_token_expire_hours: int = 24
    otp_expire_minutes: int = 10
    account_lockout_minutes: int = 30
    auth_failed_attempt_limit: int = 3
    dev_expose_otp: bool | None = None
    staging_login_otp: str | None = None
    trusted_proxy_ips: str = "127.0.0.1,::1"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        hide_input_in_errors=True,
    )

    @model_validator(mode="after")
    def validate_business_currency_environment(self) -> "Settings":
        if self.backup_encryption_password_file:
            self.backup_encryption_password = read_private_secret_file(
                self.backup_encryption_password_file,
                setting_name="BACKUP_ENCRYPTION_PASSWORD",
            )
        disposable_environment = self.app_env.strip().lower() in {"development", "test", "local"}
        if self.business_currency != DEFAULT_BUSINESS_CURRENCY and not disposable_environment:
            raise ValueError(
                "Changing the deployed operating currency requires approved historical "
                "currency reconciliation and a separate data migration."
            )
        return self

    def business_policy(self) -> BusinessPolicyResponse:
        return BusinessPolicyResponse(
            business_currency=self.business_currency,
            business_timezone=self.business_timezone,
            material_approval_threshold=self.material_approval_threshold,
        )

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.backend_cors_origins.split(",") if origin.strip()]

    @property
    def normalized_frontend_base_url(self) -> str | None:
        if self.frontend_base_url is None:
            return None
        normalized = self.frontend_base_url.strip().rstrip("/")
        return normalized or None

    @property
    def trusted_proxy_ips_list(self) -> list[str]:
        return [ip.strip() for ip in self.trusted_proxy_ips.split(",") if ip.strip()]

    @property
    def otp_hardened_env(self) -> bool:
        """Environments where OTPs must never be echoed back to the caller."""
        return self.app_env.lower() in {"production", "staging"}

    @property
    def should_expose_dev_otp(self) -> bool:
        # Hard gate first: an explicit DEV_EXPOSE_OTP=true must not leak codes in prod/staging.
        if self.otp_hardened_env:
            return False
        if self.dev_expose_otp is not None:
            return self.dev_expose_otp
        return self.app_env.lower() in {"development", "test", "local"}

    @property
    def staging_login_otp_enabled(self) -> bool:
        # Same environment-first gate: the fixed UAT code is honoured only in staging,
        # never in production, regardless of any other flag.
        if self.app_env.lower() != "staging":
            return False
        return (
            self.staging_login_otp is not None
            and len(self.staging_login_otp) == 6
            and self.staging_login_otp.isdigit()
        )

    @property
    def exception_email_recipients_list(self) -> list[str]:
        return [
            recipient.strip()
            for recipient in self.exception_email_recipients.split(",")
            if recipient.strip()
        ]

    @property
    def should_send_exception_emails(self) -> bool:
        if self.exception_email_enabled is not None:
            return self.exception_email_enabled
        return self.app_env.lower() in {"production", "prod", "staging"}

    @property
    def minio_signed_url_endpoint(self) -> str:
        return self.minio_public_endpoint or self.minio_endpoint

    @property
    def minio_signed_url_secure(self) -> bool:
        if self.minio_public_secure is not None:
            return self.minio_public_secure
        return self.minio_secure


@lru_cache
def get_settings() -> Settings:
    return Settings()
