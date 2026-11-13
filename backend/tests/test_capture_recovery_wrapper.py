from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

WRAPPER = Path(__file__).resolve().parents[2] / "deploy" / "capture-recovery-set.sh"
SHA = "a" * 40
IMAGE = "sha256:" + "b" * 64

DOCKER = r"""#!/usr/bin/env python3
import json, os, pathlib, sys
path = pathlib.Path(os.environ['FIXTURE_WRITER_STATE'])
state = json.loads(path.read_text())
events = pathlib.Path(os.environ['FIXTURE_EVENTS'])
args = sys.argv[1:]

def record(action, set_id):
    with events.open('a') as output:
        output.write(f'{action}:{set_id}\n')

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
    record('stop', len(args) - 1)
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
    if os.environ.get('FIXTURE_FAILURE') in {'preflight', 'preflight-and-status'}:
        sys.exit(1)
    if os.environ.get('FIXTURE_FAILURE') == 'invalid-limits':
        print('30 1 unexpected')
        sys.exit(0)
    print('30 1')
    if os.environ.get('FIXTURE_FAILURE') == 'failed-after-limits':
        sys.exit(1)
elif 'capture' in args:
    assert not any(state.values())
    volume = next(arg for arg in args if arg.endswith(':/capture'))
    destination = pathlib.Path(volume.removesuffix(':/capture')) / 'set'
    destination.mkdir(mode=0o700)
    (destination / 'application.sql.gz.enc').write_text('fixture data')
    set_id = 1 + events.read_text().count('capture:')
    record('capture', set_id)
    if os.environ.get('FIXTURE_FAILURE') == 'capture':
        sys.exit(124)
    (destination / 'manifest.json').write_text(str(set_id))
elif 'publish' in args:
    assert state['garrison-portal-backend-1'] and state['garrison-portal-nginx-1']
    volume = next(arg for arg in args if arg.endswith(':/capture:ro'))
    set_path = pathlib.Path(volume.removesuffix(':/capture:ro'))
    set_id = (set_path / 'manifest.json').read_text()
    record('publish', set_id)
    if os.environ.get('FIXTURE_FAILURE') == 'publication':
        sys.exit(1)
    volume = next(arg for arg in args if arg.endswith(':/receipts'))
    root = pathlib.Path(volume.removesuffix(':/receipts'))
    (root / 'latest-success.json').write_text(set_id)
    remote = pathlib.Path(os.environ['FIXTURE_REMOTE'])
    (remote / f'complete-{set_id}').write_bytes((set_path / 'application.sql.gz.enc').read_bytes())
elif 'publish-attempt' in args:
    assert args[args.index('--env-file') + 1] == os.environ['RECOVERY_PUBLISH_ENV']
    assert args[args.index('publish-attempt'):] == [
        'publish-attempt', '/receipts/last-attempt.json', '--policy', '/policy.json',
        '--inventory', '/capture-inventory.json',
    ]
    root = pathlib.Path(os.environ['FIXTURE_EVIDENCE'])
    receipt = root / 'last-attempt.json'
    assert [args[i + 1] for i, arg in enumerate(args) if arg == '-v'] == [
        f"{os.environ['RECOVERY_POLICY']}:/policy.json:ro",
        f"{os.environ['BACKUP_AUTH_KEY_FILE']}:/recovery-key:ro",
        f'{receipt}:/receipts/last-attempt.json:ro',
        f"{os.environ['RECOVERY_CAPTURE_TEMPLATE']}:/capture-inventory.json:ro",
    ]
    assert 'BACKUP_AUTH_KEY_FILE=/recovery-key' in args
    assert 'BACKUP_AUTH_KEY_ID=fixture' in args
    raw = receipt.read_bytes()
    attempt = json.loads(raw)
    assert state['garrison-portal-backend-1'] and state['garrison-portal-nginx-1']
    if attempt['phase'] == 'resume':
        assert not state['garrison-portal-grafana-1']
    if os.environ.get('FIXTURE_FAILURE') in {'status', 'preflight-and-status'}:
        sys.exit(1)
    remote = pathlib.Path(os.environ['FIXTURE_REMOTE'])
    with (remote / 'attempts.jsonl').open('ab') as output:
        output.write(raw + b'\n')
else:
    sys.exit(2)
"""


def executable(directory: Path, name: str, source: str) -> None:
    target = directory / name
    target.write_text(source)
    target.chmod(0o700)


@dataclass
class ScheduledCapture:
    script: Path
    env: dict[str, str]
    evidence: Path
    before: dict[str, bool]
    writer_state: Path
    events: Path
    remote: Path

    def run(
        self, failure: str = "", *, now: str = "2026-11-12T17:00:00Z"
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["/bin/bash", str(self.script)],
            env={**self.env, "FIXTURE_FAILURE": failure, "FIXTURE_UTC": now},
            capture_output=True,
            text=True,
        )


@pytest.fixture
def scheduled_capture(tmp_path: Path) -> ScheduledCapture:
    commands = tmp_path / "bin"
    commands.mkdir()
    executable(commands, "docker", DOCKER)
    executable(
        commands,
        "flock",
        "#!/bin/bash\n[[ $* == '-n 9' && ${FIXTURE_FAILURE:-} != lock ]]\n",
    )
    executable(
        commands,
        "timeout",
        """#!/bin/bash
if [[ " $* " == *' publish-attempt '* && "$1" != 60 ]]; then exit 2; fi
shift
exec "$@"
""",
    )
    executable(
        commands,
        "stat",
        """#!/usr/bin/env python3
import pathlib, stat, sys
info = pathlib.Path(sys.argv[3]).stat()
match sys.argv[2]:
    case '%u': print(0)
    case '%a': print(f'{stat.S_IMODE(info.st_mode):o}')
    case '%s': print(info.st_size)
    case _: sys.exit(2)
""",
    )
    executable(commands, "readlink", '#!/bin/bash\nprintf "%s\\n" "$FIXTURE_RELEASE"\n')
    executable(commands, "realpath", '#!/bin/bash\nprintf "%s\\n" "$3"\n')
    executable(commands, "date", '#!/bin/bash\nprintf "%s\\n" "$FIXTURE_UTC"\n')
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
    events = tmp_path / "events.txt"
    events.write_text("")
    remote = tmp_path / "remote"
    remote.mkdir()
    evidence = base / "recovery" / "scheduled"
    configuration = tmp_path / "nonsecret-configuration"
    configuration.mkdir(mode=0o700)
    files = {
        "RECOVERY_POLICY": "{}",
        "RECOVERY_CAPTURE_TEMPLATE": json.dumps(
            {
                "source_sha": SHA,
                "source_environment": "production",
                "configuration_sha256": "c" * 64,
                "image_digests": {"backend": IMAGE},
            }
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
        FIXTURE_EVENTS=str(events),
        FIXTURE_EVIDENCE=str(evidence),
        FIXTURE_REMOTE=str(remote),
        FIXTURE_RELEASE=str(release),
    )
    shell = (
        WRAPPER.read_text()
        .replace("export PATH=/usr/sbin:/usr/bin:/sbin:/bin", f'export PATH="{commands}:$PATH"', 1)
        .replace("base=/opt/garrison-portal", f'base="{base}"', 1)
    )
    fixture = tmp_path / "wrapper.sh"
    fixture.write_text(shell)
    return ScheduledCapture(fixture, env, evidence, before, state, events, remote)


@pytest.mark.parametrize(
    ("failure", "phase"), [("", "complete"), ("capture", "capture"), ("resume", "resume")]
)
def test_capture_wrapper_preserves_writer_state_and_failure_receipts(
    scheduled_capture: ScheduledCapture, failure: str, phase: str
) -> None:
    evidence = scheduled_capture.evidence
    latest_success = evidence / "latest-success.json"
    remote = scheduled_capture.remote
    if failure == "resume":
        result = scheduled_capture.run(now="2026-11-12T16:00:00Z")
        assert result.returncode == 0, result.stderr
        assert latest_success.read_text() == "1"

    result = scheduled_capture.run(failure)
    assert (result.returncode == 0) == (not failure), result.stderr
    assert latest_success.exists() == (failure != "capture")
    receipt = (evidence / "last-attempt.json").read_bytes()
    assert (remote / "attempts.jsonl").read_bytes().splitlines()[-1] == receipt
    assert json.loads(receipt)["phase"] == phase
    before = scheduled_capture.before.copy()
    if failure == "resume":
        before["garrison-portal-grafana-1"] = False
    assert json.loads(scheduled_capture.writer_state.read_text()) == before
    scratch = evidence / ".scheduled-capture"
    if failure == "resume":
        assert result.returncode == 1
        assert json.loads(receipt)["outcome"] == "fail"
        assert latest_success.read_text() == "1"
        assert (remote / "complete-1").read_bytes() == b"fixture data"
        assert not (remote / "complete-2").exists()
        assert (scratch / "set" / "manifest.json").read_text() == "2"
        assert scheduled_capture.run().returncode != 0
        assert scheduled_capture.events.read_text().splitlines() == [
            "stop:4",
            "capture:1",
            "publish:1",
            "stop:4",
            "capture:2",
        ]
    else:
        assert not any(path.is_dir() for path in evidence.iterdir())


def test_successes_release_only_the_current_capture_workspace(
    scheduled_capture: ScheduledCapture,
) -> None:
    evidence = scheduled_capture.evidence
    historical = evidence / "capture-abcdefgh" / "set"
    historical.mkdir(parents=True, mode=0o700)
    evidence.chmod(0o700)
    (historical / "manifest.json").write_text("historical")

    for expected_id in ("1", "2"):
        result = scheduled_capture.run()
        assert result.returncode == 0, result.stderr
        assert (evidence / "latest-success.json").read_text() == expected_id
        assert json.loads((evidence / "last-attempt.json").read_text())["phase"] == "complete"
        assert [path for path in evidence.iterdir() if path.is_dir()] == [historical.parent]
        assert (historical / "manifest.json").read_text() == "historical"


def test_failed_publication_retries_the_same_capture_without_pausing_writers_again(
    scheduled_capture: ScheduledCapture,
) -> None:
    assert scheduled_capture.run().returncode == 0
    evidence = scheduled_capture.evidence
    success = evidence / "latest-success.json"
    attempt = evidence / "last-attempt.json"
    assert success.read_text() == "1"

    for minute in (1, 2):
        result = scheduled_capture.run("publication", now=f"2026-11-12T17:0{minute}:00Z")
        assert result.returncode != 0
        assert success.read_text() == "1"
        failure = json.loads(attempt.read_text())
        assert (failure["phase"], failure["outcome"]) == ("publication", "fail")
        pending = evidence / ".scheduled-capture" / "set"
        assert (pending / "manifest.json").read_text() == "2"
        assert (pending / "application.sql.gz.enc").read_text() == "fixture data"
        assert json.loads(scheduled_capture.writer_state.read_text()) == scheduled_capture.before

    result = scheduled_capture.run(now="2026-11-12T17:03:00Z")
    assert result.returncode == 0, result.stderr
    assert success.read_text() == "2"
    assert not pending.exists()
    receipt = json.loads(attempt.read_text())
    assert (receipt["phase"], receipt["outcome"]) == ("complete", "pass")
    assert receipt["started_at_utc"] == "2026-11-12T17:01:00Z"
    assert scheduled_capture.events.read_text().splitlines() == [
        "stop:4",
        "capture:1",
        "publish:1",
        "stop:4",
        "capture:2",
        "publish:2",
        "publish:2",
        "publish:2",
    ]


def test_status_transport_failure_keeps_local_receipt_and_verified_set(
    scheduled_capture: ScheduledCapture,
) -> None:
    evidence = scheduled_capture.evidence
    remote = scheduled_capture.remote
    result = scheduled_capture.run(now="2026-11-12T16:00:00Z")
    assert result.returncode == 0, result.stderr
    published_attempt = (remote / "attempts.jsonl").read_bytes()
    previous_backup = (remote / "complete-1").read_bytes()

    result = scheduled_capture.run("status")
    assert result.returncode == 1
    attempt = json.loads((evidence / "last-attempt.json").read_bytes())
    assert (attempt["phase"], attempt["outcome"]) == ("complete", "pass")
    assert (evidence / "latest-success.json").read_text() == "2"
    assert (remote / "complete-2").read_bytes() == b"fixture data"
    assert (remote / "complete-1").read_bytes() == previous_backup
    assert (remote / "attempts.jsonl").read_bytes() == published_attempt
    assert not (evidence / ".scheduled-capture").exists()


def test_lock_failure_leaves_previous_attempt_and_backup_unchanged(
    scheduled_capture: ScheduledCapture,
) -> None:
    result = scheduled_capture.run()
    assert result.returncode == 0, result.stderr
    evidence = scheduled_capture.evidence
    remote = scheduled_capture.remote
    lock = evidence.parents[1] / "deploy" / "deploy.lock"
    lock.write_text("existing owner")
    paths = (
        lock,
        evidence / "last-attempt.json",
        evidence / "latest-success.json",
        remote / "attempts.jsonl",
        remote / "complete-1",
        scheduled_capture.events,
    )
    before = [path.read_bytes() for path in paths]

    assert scheduled_capture.run("lock").returncode != 0
    assert [path.read_bytes() for path in paths] == before


@pytest.mark.parametrize(
    "failure", ["preflight", "invalid-limits", "failed-after-limits", "preflight-and-status"]
)
def test_policy_preflight_failure_records_status_without_touching_writers_or_last_good(
    scheduled_capture: ScheduledCapture, failure: str
) -> None:
    assert scheduled_capture.run().returncode == 0
    evidence = scheduled_capture.evidence
    remote = scheduled_capture.remote
    paths = (
        evidence / "latest-success.json",
        remote / "complete-1",
        scheduled_capture.events,
        scheduled_capture.writer_state,
    )
    before = [path.read_bytes() for path in paths]
    result = scheduled_capture.run(failure, now="2026-11-12T18:00:00Z")

    assert result.returncode != 0
    local = json.loads((evidence / "last-attempt.json").read_bytes())
    assert (local["phase"], local["outcome"]) == ("preflight", "fail")
    assert local["started_at_utc"] == "2026-11-12T18:00:00Z"
    remote_attempts = (remote / "attempts.jsonl").read_text().splitlines()
    if failure == "preflight-and-status":
        assert len(remote_attempts) == 1
        assert "status publication failed" in result.stderr
    else:
        assert len(remote_attempts) == 2 and json.loads(remote_attempts[-1]) == local
    assert [path.read_bytes() for path in paths] == before
    assert not (evidence / ".scheduled-capture").exists()


@pytest.mark.parametrize("symlink", [False, True])
def test_wrapper_leaves_unknown_workspace_untouched(
    scheduled_capture: ScheduledCapture, tmp_path: Path, symlink: bool
) -> None:
    evidence = scheduled_capture.evidence
    evidence.mkdir(parents=True, mode=0o700)
    scratch = evidence / ".scheduled-capture"
    target = tmp_path / "external-backup" if symlink else scratch
    target.mkdir(mode=0o700)
    if symlink:
        scratch.symlink_to(target, target_is_directory=True)
    (target / "manifest.json").write_text("keep")

    assert scheduled_capture.run().returncode != 0
    assert (target / "manifest.json").read_text() == "keep"
    assert scratch.is_symlink() == symlink
    assert scheduled_capture.events.read_text() == ""
