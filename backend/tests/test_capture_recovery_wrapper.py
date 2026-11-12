from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

WRAPPER = Path(__file__).resolve().parents[2] / "deploy" / "capture-recovery-set.sh"
SHA = "a" * 40
IMAGE = "sha256:" + "b" * 64

DOCKER = """#!/usr/bin/env python3
import json, os, pathlib, sys
path = pathlib.Path(os.environ['FIXTURE_WRITER_STATE'])
state = json.loads(path.read_text())
args = sys.argv[1:]
if args[0] == 'inspect':
    if '.Image' in args[2]:
        print(os.environ['FIXTURE_IMAGE'])
    elif 'Networks' in args[2]:
        print('private-fixture-network')
    elif 'Health' in args[2]:
        print('running' if state[args[3]] else 'stopped')
    else:
        print(str(state[args[3]]).lower())
elif args[0] == 'stop':
    for name in args[1:]:
        assert state[name]
        state[name] = False
    path.write_text(json.dumps(state))
elif args[0] == 'start':
    if os.environ.get('FIXTURE_FAILURE') == 'resume' and args[1] == 'garrison-portal-grafana-1':
        sys.exit(1)
    for name in args[1:]:
        assert name != 'garrison-portal-celery_beat-1'
        state[name] = True
    path.write_text(json.dumps(state))
elif 'policy-check' in args:
    print('30 1')
elif 'capture' in args:
    assert not any(state.values())
    volume = next(arg for arg in args if arg.endswith(':/capture'))
    (pathlib.Path(volume.removesuffix(':/capture')) / 'set').mkdir()
elif 'publish' in args:
    assert state['garrison-portal-backend-1'] and state['garrison-portal-nginx-1']
    volume = next(arg for arg in args if arg.endswith(':/receipts'))
    root = pathlib.Path(volume.removesuffix(':/receipts'))
    (root / 'latest-success.json').write_text('published')
else:
    sys.exit(2)
"""


def executable(directory: Path, name: str, source: str) -> None:
    target = directory / name
    target.write_text(source)
    target.chmod(0o700)


@pytest.mark.parametrize(
    ("failure", "phase"), [("", "complete"), ("capture", "capture"), ("resume", "resume")]
)
def test_capture_wrapper_preserves_writer_state_and_failure_receipts(
    tmp_path: Path, failure: str, phase: str
) -> None:
    commands = tmp_path / "bin"
    commands.mkdir()
    executable(commands, "docker", DOCKER)
    executable(commands, "flock", "#!/bin/bash\n[[ $* == '-n 9' ]]\n")
    executable(
        commands,
        "timeout",
        """#!/bin/bash
if [[ ${FIXTURE_FAILURE:-} == capture && " $* " == *'scripts.backup_set capture '* ]]; then
    exit 124
fi
shift
exec "$@"
""",
    )
    executable(
        commands,
        "stat",
        """#!/bin/bash
case "$2" in %u) echo 0;; %a) echo 600;; %s) echo 32;; *) exit 2;; esac
""",
    )
    executable(commands, "readlink", '#!/bin/bash\nprintf "%s\\n" "$FIXTURE_RELEASE"\n')
    executable(commands, "realpath", '#!/bin/bash\nprintf "%s\\n" "$3"\n')
    base = tmp_path / "portal"
    release = base / "releases" / SHA
    release.mkdir(parents=True)
    (release / "SOURCE_COMMIT").write_text(SHA)
    (base / "deploy").mkdir()
    (base / "deploy" / "current").symlink_to(release)
    before = {
        f"garrison-portal-{name}-1": name != "celery_beat"
        for name in ("nginx", "celery_beat", "celery_worker", "backend", "grafana")
    }
    state = tmp_path / "writers.json"
    state.write_text(json.dumps(before))
    configuration = tmp_path / "nonsecret-configuration"
    configuration.mkdir(mode=0o700)
    files = {
        "RECOVERY_POLICY": "{}",
        "RECOVERY_CAPTURE_TEMPLATE": json.dumps(
            {"source_sha": SHA, "image_digests": {"backend": IMAGE}}
        ),
        "RECOVERY_CAPTURE_ENV": "\n".join(
            f"{key}=fixture"
            for key in (
                "DATABASE_URL",
                "MINIO_ENDPOINT",
                "MINIO_BUCKET",
                "MINIO_ROOT_USER",
                "MINIO_ROOT_PASSWORD",
                "BACKUP_ENCRYPTION_PASSWORD",
            )
        ),
        "RECOVERY_PUBLISH_ENV": "\n".join(
            f"{key}=fixture"
            for key in (
                "DR_BACKUP_ENDPOINT",
                "DR_BACKUP_BUCKET",
                "DR_BACKUP_PREFIX",
                "DR_BACKUP_SECURE",
                "DR_BACKUP_ACCESS_KEY",
                "DR_BACKUP_SECRET_KEY",
            )
        ),
        "BACKUP_AUTH_KEY_FILE": "x" * 32,
    }
    env = os.environ.copy()
    for name, content in files.items():
        path = tmp_path / name
        path.write_text(content)
        path.chmod(0o600)
        env[name] = str(path)
    env.update(
        BACKUP_AUTH_KEY_ID="fixture",
        RECOVERY_CONFIGURATION_ROOT=str(configuration),
        FIXTURE_WRITER_STATE=str(state),
        FIXTURE_IMAGE=IMAGE,
        FIXTURE_FAILURE=failure,
        FIXTURE_RELEASE=str(release),
    )
    shell = (
        WRAPPER.read_text()
        .replace("export PATH=/usr/sbin:/usr/bin:/sbin:/bin", f'export PATH="{commands}:$PATH"', 1)
        .replace("base=/opt/garrison-portal", f'base="{base}"', 1)
    )
    fixture = tmp_path / "wrapper.sh"
    fixture.write_text(shell)
    result = subprocess.run(["/bin/bash", str(fixture)], env=env, capture_output=True, text=True)
    evidence = base / "recovery" / "scheduled"
    assert (result.returncode == 0) == (not failure), result.stderr
    assert (evidence / "latest-success.json").exists() == (not failure)
    assert json.loads((evidence / "last-attempt.json").read_text())["phase"] == phase
    if failure == "resume":
        before["garrison-portal-grafana-1"] = False
    assert json.loads(state.read_text()) == before
