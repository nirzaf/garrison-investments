from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MONITOR = ROOT / "deploy/garrison-grafana-tls-check"


def _install_command_stubs(tmp_path: Path) -> tuple[dict[str, str], Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    logs = tmp_path / "logger.log"
    mail = tmp_path / "docker.log"

    (bin_dir / "openssl").write_text(
        "#!/bin/sh\n"
        "case \"$*\" in\n"
        "  *s_client*)\n"
        "    for required in '-connect 127.0.0.1:443' "
        "'-servername grafana.portal.garrisons.lk' '-verify 5' "
        "'-verify_return_error' "
        "'-verify_hostname grafana.portal.garrisons.lk'; do\n"
        "      case \" $* \" in *\"$required\"*) ;; *) exit 2 ;; esac\n"
        "    done\n"
        "    test \"${VERIFY_OK:-0}\" = 0 || exit \"${VERIFY_OK:-1}\"\n"
        "    printf '%s\\n' 'Verify return code: 0 (ok)'\n"
        "    printf '%s\\n' '-----BEGIN CERTIFICATE-----' 'TEST-CERT' '-----END CERTIFICATE-----'\n"
        "    ;;\n"
        "  *-checkend\\ 604800*) exit \"${URGENT_OK:-0}\" ;;\n"
        "  *-checkend\\ 2592000*) exit \"${WARNING_OK:-0}\" ;;\n"
        "  *-enddate*) printf '%s\\n' 'notAfter=Feb 09 14:49:19 2027 GMT' ;;\n"
        "  *x509*) exit 0 ;;\n"
        "  *) exit 2 ;;\n"
        "esac\n"
    )
    (bin_dir / "logger").write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$LOGGER_CAPTURE\"\n"
    )
    (bin_dir / "docker").write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$DOCKER_CAPTURE\"\n"
        "exit \"${DOCKER_OK:-0}\"\n"
    )
    for command in bin_dir.iterdir():
        command.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "LOGGER_CAPTURE": str(logs),
            "DOCKER_CAPTURE": str(mail),
            "VERIFY_OK": "0",
            "URGENT_OK": "0",
            "WARNING_OK": "0",
            "DOCKER_OK": "0",
        }
    )
    return env, logs, mail


def _run(
    tmp_path: Path, *args: str, **overrides: str
) -> tuple[subprocess.CompletedProcess[str], str, str]:
    env, logs, mail = _install_command_stubs(tmp_path)
    env.update(overrides)
    result = subprocess.run(
        [str(MONITOR), *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    return (
        result,
        logs.read_text() if logs.exists() else "",
        mail.read_text() if mail.exists() else "",
    )


def test_grafana_certificate_monitor_logs_valid_certificate_without_alert(tmp_path: Path) -> None:
    result, logs, mail = _run(tmp_path)

    assert result.returncode == 0
    assert "event=certificate_expiry_ok synthetic=false" in logs
    assert mail == ""


def test_grafana_certificate_monitor_warns_at_30_days_and_emails_superadmin(tmp_path: Path) -> None:
    result, logs, mail = _run(tmp_path, WARNING_OK="1")

    assert result.returncode == 0
    assert "event=certificate_expiry_warning synthetic=false" in logs
    assert "info@quadrate.lk" in mail
    assert "Garrisons Grafana TLS alert" in mail


def test_grafana_certificate_monitor_urgently_alerts_at_7_days(tmp_path: Path) -> None:
    result, logs, mail = _run(tmp_path, URGENT_OK="1")

    assert result.returncode == 1
    assert "event=certificate_expiry_urgent synthetic=false" in logs
    assert "info@quadrate.lk" in mail


def test_grafana_certificate_monitor_rejects_wrong_hostname_or_chain(tmp_path: Path) -> None:
    result, logs, mail = _run(tmp_path, VERIFY_OK="1")

    assert result.returncode == 1
    assert "event=certificate_missing_or_invalid synthetic=false" in logs
    assert "info@quadrate.lk" in mail


def test_grafana_certificate_monitor_reports_alert_delivery_failure(tmp_path: Path) -> None:
    result, logs, _ = _run(tmp_path, WARNING_OK="1", DOCKER_OK="1")

    assert result.returncode == 1
    assert "event=expiry_alert_delivery_failed" in logs


def test_grafana_certificate_monitor_synthetic_warning_is_labeled(tmp_path: Path) -> None:
    result, logs, mail = _run(tmp_path, "--test-warning")

    assert result.returncode == 0
    assert "synthetic=true" in logs
    assert "[TEST]" in mail
    assert "GARRISON-GRAFANA-TLS-TEST-V01" in mail


def test_grafana_certificate_monitor_synthetic_urgent_is_labeled(tmp_path: Path) -> None:
    result, logs, mail = _run(tmp_path, "--test-urgent")

    assert result.returncode == 0
    assert "synthetic=true" in logs
    assert "[TEST]" in mail
    assert "GARRISON-GRAFANA-TLS-TEST-V01" in mail
