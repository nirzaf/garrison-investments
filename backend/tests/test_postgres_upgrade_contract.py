from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
POSTGRES_19_IMAGE = (
    "postgres:19.0-alpine3.24@sha256:"
    "8b0ff4cdf221f0c53d7fcda681d3b461be725c492cd881c5ec9c0ad25023f188"
)


def test_runtime_and_ci_use_the_same_pinned_postgres_19_image() -> None:
    expected_counts = {
        "docker-compose.yml": 1,
        "docker-compose.prod.yml": 2,
        "docker-compose.staging.yml": 2,
        ".github/workflows/ci.yml": 1,
    }

    for relative_path, expected_count in expected_counts.items():
        content = (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")
        assert content.count(POSTGRES_19_IMAGE) == expected_count, relative_path


def test_major_upgrade_uses_a_fresh_versioned_data_volume() -> None:
    for relative_path in (
        "docker-compose.yml",
        "docker-compose.prod.yml",
        "docker-compose.staging.yml",
    ):
        content = (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")
        assert "- pgdata19:/var/lib/postgresql" in content, relative_path
        assert "  pgdata19:" in content, relative_path
        assert "- pgdata:/var/lib/postgresql" not in content, relative_path


def test_backup_and_restore_client_matches_postgres_19() -> None:
    content = (REPOSITORY_ROOT / "backend/Dockerfile").read_text(encoding="utf-8")
    readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")

    assert "postgresql-client-19" in content
    assert "postgresql-client-18" not in content
    assert "#upgrade-postgresql-18-to-190" in readme
    assert "before starting PostgreSQL 18" not in readme
