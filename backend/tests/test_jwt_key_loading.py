"""C2 — a hardened deployment must never fall back to the published development keys."""

from pathlib import Path
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.config import Settings
from app.utils.security import (
    create_access_token,
    decode_access_token,
    validate_signing_keys,
)


@pytest.fixture(scope="module")
def key_pair(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    directory = tmp_path_factory.mktemp("jwt-keys")
    private_path = directory / "private.pem"
    public_path = directory / "public.pem"
    private_path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    public_path.write_bytes(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    return private_path, public_path


def use_settings(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    monkeypatch.setattr("app.utils.security.get_settings", lambda: settings)


@pytest.mark.parametrize("app_env", ["production", "staging", "PRODUCTION"])
def test_hardened_env_without_key_paths_refuses_to_start(
    monkeypatch: pytest.MonkeyPatch, app_env: str
) -> None:
    use_settings(monkeypatch, Settings(app_env=app_env))

    with pytest.raises(RuntimeError, match="JWT_PRIVATE_KEY_PATH"):
        validate_signing_keys()


def test_hardened_env_with_missing_key_file_refuses_to_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    use_settings(
        monkeypatch,
        Settings(
            app_env="production",
            jwt_private_key_path=str(tmp_path / "absent-private.pem"),
            jwt_public_key_path=str(tmp_path / "absent-public.pem"),
        ),
    )

    with pytest.raises(RuntimeError, match="missing or unreadable"):
        validate_signing_keys()


def test_hardened_env_with_corrupt_pem_refuses_to_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    private_path = tmp_path / "private.pem"
    public_path = tmp_path / "public.pem"
    private_path.write_text("-----BEGIN PRIVATE KEY-----\nnot-a-key\n-----END PRIVATE KEY-----\n")
    public_path.write_text("-----BEGIN PUBLIC KEY-----\nnot-a-key\n-----END PUBLIC KEY-----\n")
    use_settings(
        monkeypatch,
        Settings(
            app_env="production",
            jwt_private_key_path=str(private_path),
            jwt_public_key_path=str(public_path),
        ),
    )

    with pytest.raises(RuntimeError, match="not a valid PEM key"):
        validate_signing_keys()


def test_hardened_env_rejects_a_public_key_in_the_private_slot(
    monkeypatch: pytest.MonkeyPatch, key_pair: tuple[Path, Path]
) -> None:
    private_path, public_path = key_pair
    use_settings(
        monkeypatch,
        Settings(
            app_env="staging",
            jwt_private_key_path=str(public_path),
            jwt_public_key_path=str(public_path),
        ),
    )

    with pytest.raises(RuntimeError, match="not a valid PEM key"):
        validate_signing_keys()
    assert private_path.exists()


def test_hardened_env_with_real_keys_starts_and_signs(
    monkeypatch: pytest.MonkeyPatch, key_pair: tuple[Path, Path]
) -> None:
    private_path, public_path = key_pair
    use_settings(
        monkeypatch,
        Settings(
            app_env="production",
            jwt_private_key_path=str(private_path),
            jwt_public_key_path=str(public_path),
        ),
    )

    validate_signing_keys()
    user_id = uuid4()
    token, _ = create_access_token(user_id, "managing_director")
    assert decode_access_token(token)["sub"] == str(user_id)


@pytest.mark.parametrize("app_env", ["development", "test", "local"])
def test_dev_env_without_keys_uses_the_embedded_fallback(
    monkeypatch: pytest.MonkeyPatch, app_env: str
) -> None:
    use_settings(monkeypatch, Settings(app_env=app_env))

    validate_signing_keys()
    user_id = uuid4()
    token, _ = create_access_token(user_id, "group_project_manager")
    assert decode_access_token(token)["sub"] == str(user_id)


def test_dev_env_with_unreadable_key_path_still_falls_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    use_settings(
        monkeypatch,
        Settings(
            app_env="development",
            jwt_private_key_path=str(tmp_path / "absent.pem"),
            jwt_public_key_path=str(tmp_path / "absent.pem"),
        ),
    )

    validate_signing_keys()
    token, _ = create_access_token(uuid4(), "managing_director")
    assert decode_access_token(token)["type"] == "access"


def test_hardened_env_never_falls_back_after_key_files_disappear(
    monkeypatch: pytest.MonkeyPatch, key_pair: tuple[Path, Path], tmp_path: Path
) -> None:
    private_path = tmp_path / "private.pem"
    public_path = tmp_path / "public.pem"
    private_path.write_bytes(key_pair[0].read_bytes())
    public_path.write_bytes(key_pair[1].read_bytes())
    use_settings(
        monkeypatch,
        Settings(
            app_env="production",
            jwt_private_key_path=str(private_path),
            jwt_public_key_path=str(public_path),
        ),
    )

    validate_signing_keys()
    token, _ = create_access_token(uuid4(), "group_project_manager")
    private_path.unlink()
    public_path.unlink()

    with pytest.raises(RuntimeError, match="JWT_PRIVATE_KEY_PATH"):
        create_access_token(uuid4(), "group_project_manager")
    with pytest.raises(RuntimeError, match="JWT_PUBLIC_KEY_PATH"):
        decode_access_token(token)
