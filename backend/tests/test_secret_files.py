from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings, get_settings
from app.utils.secret_files import read_private_secret_file


def private_secret(tmp_path: Path, name: str = "backup-key") -> Path:
    path = tmp_path / name
    path.write_text("synthetic-backup-key\n", encoding="utf-8")
    path.chmod(0o600)
    return path


def test_settings_loads_backup_secret_from_private_file_and_hides_repr(tmp_path: Path) -> None:
    path = private_secret(tmp_path)

    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]  # pydantic-settings runtime override
        app_env="test",
        backup_encryption_password="",
        backup_encryption_key_file=str(path),
    )

    assert settings.backup_encryption_password == "synthetic-backup-key"
    assert "synthetic-backup-key" not in repr(settings)
    assert "backup_encryption_password" not in repr(settings)


def test_settings_reads_file_path_from_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = private_secret(tmp_path)
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("BACKUP_ENCRYPTION_KEY_FILE", str(path))
    monkeypatch.delenv("BACKUP_ENCRYPTION_PASSWORD", raising=False)
    get_settings.cache_clear()
    try:
        assert get_settings().backup_encryption_password == "synthetic-backup-key"
    finally:
        get_settings.cache_clear()


def test_secret_file_rejects_group_or_world_access(tmp_path: Path) -> None:
    path = private_secret(tmp_path)
    path.chmod(0o640)

    with pytest.raises(ValueError, match="owner-only"):
        read_private_secret_file(str(path), setting_name="BACKUP_ENCRYPTION_PASSWORD")


def test_secret_file_rejects_symlinks(tmp_path: Path) -> None:
    target = private_secret(tmp_path)
    link = tmp_path / "backup-key-link"
    link.symlink_to(target)

    with pytest.raises(ValueError, match="private regular file"):
        read_private_secret_file(str(link), setting_name="BACKUP_ENCRYPTION_PASSWORD")


@pytest.mark.parametrize("value", ["", "\n", "  \n"])
def test_secret_file_rejects_empty_content(tmp_path: Path, value: str) -> None:
    path = tmp_path / "backup-key"
    path.write_text(value, encoding="utf-8")
    path.chmod(0o600)

    with pytest.raises(ValueError, match="must not be empty"):
        read_private_secret_file(str(path), setting_name="BACKUP_ENCRYPTION_PASSWORD")


def test_secret_file_rejects_relative_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    path = private_secret(tmp_path)

    with pytest.raises(ValueError, match="absolute"):
        read_private_secret_file(path.name, setting_name="BACKUP_ENCRYPTION_PASSWORD")


def test_secret_file_rejects_oversized_content(tmp_path: Path) -> None:
    path = tmp_path / "backup-key"
    path.write_bytes(b"x" * (64 * 1024 + 1))
    path.chmod(0o600)

    with pytest.raises(ValueError, match="allowed size"):
        read_private_secret_file(str(path), setting_name="BACKUP_ENCRYPTION_PASSWORD")


def test_scheduled_backup_accepts_file_loaded_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace
    from unittest.mock import Mock

    from app.tasks import backup as backup_task

    path = private_secret(tmp_path)
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]  # pydantic-settings runtime override
        app_env="test",
        backup_encryption_key_file=str(path),
    )
    attempts: list[str] = []
    monkeypatch.setattr(backup_task, "get_settings", lambda: settings)
    monkeypatch.setattr(
        backup_task, "_record_local_attempt_best_effort", attempts.append
    )
    subprocess = Mock(return_value=SimpleNamespace(stdout="Encrypted backup uploaded\n"))
    monkeypatch.setattr(backup_task, "subprocess", SimpleNamespace(run=subprocess))

    assert backup_task.run_database_backup() == "Encrypted backup uploaded"
    assert attempts == ["pass"]
    assert subprocess.call_args.args[0][1:3] == ["-m", "scripts.backup"]


def test_scheduled_backup_fails_closed_without_encryption_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace
    from unittest.mock import Mock

    from app.tasks import backup as backup_task

    attempts: list[str] = []
    subprocess = Mock()
    monkeypatch.setattr(
        backup_task,
        "get_settings",
        lambda: SimpleNamespace(backup_encryption_password=None),
    )
    monkeypatch.setattr(
        backup_task, "_record_local_attempt_best_effort", attempts.append
    )
    monkeypatch.setattr(backup_task, "subprocess", SimpleNamespace(run=subprocess))

    with pytest.raises(RuntimeError, match="backup-encryption secret"):
        backup_task.run_database_backup()

    assert attempts == ["fail"]
    subprocess.assert_not_called()
