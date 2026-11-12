"""Write-once publication and independent readback for authenticated recovery sets."""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Iterator
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from time import monotonic
from typing import BinaryIO

import urllib3
from minio import Minio
from minio.error import S3Error

from scripts.backup_set_contract import (
    SET_ID,
    BackupSetError,
    DestinationIdentity,
    PublicationReceipt,
    RecoveryPolicy,
    ScheduledAttemptReceipt,
    read_policy,
    verify_publication_receipt,
    verify_scheduled_attempt,
)

COMPLETE = "complete.json"
IDENTITY = "manifest.sha256"
MISSING = {"NoSuchKey", "NoSuchObject"}
CHUNK = 1024 * 1024
MAX_MANIFEST_BYTES = 64 * CHUNK
MAX_SCHEDULED_ATTEMPT_BYTES = 16 * 1024
SCHEDULED_ATTEMPT = "last-scheduled-attempt.json"


class RecoveryStore:
    def __init__(self, destination: DestinationIdentity, *, timeout: float = 60) -> None:
        try:
            configured = DestinationIdentity(
                endpoint=os.environ["DR_BACKUP_ENDPOINT"],
                bucket=os.environ["DR_BACKUP_BUCKET"],
                prefix=os.environ["DR_BACKUP_PREFIX"],
                secure=os.environ["DR_BACKUP_SECURE"].lower() == "true",
            )
            access_key = os.environ["DR_BACKUP_ACCESS_KEY"]
            secret_key = os.environ["DR_BACKUP_SECRET_KEY"]
        except (KeyError, ValueError):
            raise BackupSetError(
                "Independent backup destination configuration is incomplete."
            ) from None
        if (
            os.environ["DR_BACKUP_SECURE"].lower() not in {"true", "false"}
            or configured != destination
            or not access_key
            or not secret_key
        ):
            raise BackupSetError("Independent backup destination differs from its approved policy.")
        self.destination = destination
        self.http = urllib3.PoolManager(
            cert_reqs="CERT_REQUIRED",
            timeout=urllib3.Timeout(connect=min(10, timeout), read=timeout),
            retries=False,
        )
        self.client = Minio(
            destination.endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=destination.secure,
            http_client=self.http,
        )

    def key(self, set_id: str, name: str) -> str:
        if not re.fullmatch(SET_ID, set_id) or not re.fullmatch(
            r"[a-zA-Z0-9][a-zA-Z0-9_.-]+", name
        ):
            raise BackupSetError("Unsafe backup set or remote artifact name.")
        return f"{self.destination.prefix}/{set_id}/{name}"

    def read(self, key: str, limit: int) -> bytes | None:
        try:
            response = self.client.get_object(self.destination.bucket, key)
        except S3Error as error:
            if error.code in MISSING:
                return None
            raise
        try:
            value = response.read(limit + 1)
            if len(value) > limit:
                raise BackupSetError("Independent backup metadata exceeds its allowed size.")
            return value
        finally:
            response.close()
            response.release_conn()

    def verify(self, key: str, digest: str, size: int, *, output: BinaryIO | None = None) -> bool:
        try:
            response = self.client.get_object(self.destination.bucket, key)
        except S3Error as error:
            if error.code in MISSING:
                return False
            raise
        try:
            hashed = hashlib.sha256()
            total = 0
            while block := response.read(CHUNK):
                total += len(block)
                if total > size:
                    raise BackupSetError(
                        "Independent backup artifact differs from its expected size."
                    )
                hashed.update(block)
                if output:
                    output.write(block)
            if total != size or hashed.hexdigest() != digest:
                raise BackupSetError("Independent backup artifact failed readback verification.")
            return True
        finally:
            response.close()
            response.release_conn()

    def put_once(self, key: str, source: bytes | BinaryIO, size: int) -> bool:
        # The SDK presigns the destination. The conditional header keeps object creation
        # atomic even if a second authorized publisher races a retry of the same set.
        url = self.client.presigned_put_object(self.destination.bucket, key)
        response = self.http.request(
            "PUT",
            url,
            body=source,
            headers={"If-None-Match": "*", "Content-Length": str(size)},
            redirect=False,
            preload_content=False,
        )
        try:
            if response.status == 412:
                return False
            if response.status not in (200, 201, 204):
                raise BackupSetError("Independent backup destination rejected an immutable upload.")
            return True
        finally:
            response.close()
            response.release_conn()

    def put_verified_file(self, key: str, path: Path, digest: str, size: int) -> None:
        if self.verify(key, digest, size):
            return
        with path.open("rb") as source:
            self.put_once(key, source, size)
        if not self.verify(key, digest, size):
            raise BackupSetError("Independent backup artifact is missing after publication.")

    @property
    def scheduled_attempt_key(self) -> str:
        return f"{self.destination.prefix}/{SCHEDULED_ATTEMPT}"

    def put_scheduled_attempt(self, raw: bytes) -> None:
        if not 0 < len(raw) <= MAX_SCHEDULED_ATTEMPT_BYTES:
            raise BackupSetError("Scheduled backup attempt metadata exceeds its allowed size.")
        # The scheduler's host lock serializes updates to this single status object.
        key = self.scheduled_attempt_key
        self.client.put_object(
            self.destination.bucket, key, BytesIO(raw), len(raw), content_type="application/json"
        )
        if self.read(key, MAX_SCHEDULED_ATTEMPT_BYTES) != raw:
            raise BackupSetError("Scheduled backup attempt failed independent readback.")

    def complete_keys(self) -> Iterator[str]:
        prefix = self.destination.prefix + "/"
        pattern = re.compile(r"[a-f0-9]{32}/complete\.json")
        for item in self.client.list_objects(
            self.destination.bucket, prefix=prefix, recursive=True
        ):
            if pattern.fullmatch(item.object_name.removeprefix(prefix)):
                yield item.object_name

    def remove(self, key: str) -> None:
        self.client.remove_object(self.destination.bucket, key)


def complete_receipt(
    store: RecoveryStore,
    key: str,
    policy: RecoveryPolicy,
    policy_sha256: str,
    *,
    key_file: Path,
    key_id: str,
) -> PublicationReceipt:
    data = store.read(key, CHUNK)
    if data is None:
        raise BackupSetError("Independent backup set has no complete receipt.")
    receipt = verify_publication_receipt(data, key_file=key_file, key_id=key_id)
    if (
        receipt.destination_identity != policy.destination_identity
        or receipt.source_environment != policy.source_environment
        or receipt.policy_sha256 != policy_sha256
        or receipt.policy_revision != policy.revision
        or key != store.key(receipt.backup_set_id, COMPLETE)
    ):
        raise BackupSetError("Independent backup receipt does not match the approved scope.")
    return receipt


def retention_candidates(
    receipts: list[PublicationReceipt], policy: RecoveryPolicy, at: datetime
) -> list[PublicationReceipt]:
    rules = policy.retention_rules
    ordered = sorted(receipts, key=lambda item: item.snapshot_at_utc, reverse=True)
    retained = set(rules.held_set_ids)
    retained.update(item.backup_set_id for item in ordered[: rules.keep_last_good])
    daily_cutoff = at - timedelta(days=rules.daily_days)
    current_month = at.year * 12 + at.month
    selected_months: set[int] = set()
    for item in ordered:
        snapshot = item.snapshot_at_utc
        month = snapshot.year * 12 + snapshot.month
        if snapshot >= daily_cutoff:
            retained.add(item.backup_set_id)
        if current_month - month < rules.monthly_months and month not in selected_months:
            selected_months.add(month)
            retained.add(item.backup_set_id)
    return [item for item in ordered if item.backup_set_id not in retained]


def read_latest_publication(
    policy_path: Path,
    *,
    key_file: Path,
    key_id: str,
    timeout: float = 60,
    expected_policy_sha256: str | None = None,
) -> PublicationReceipt:
    """Read freshness directly using independently supplied read-only credentials."""
    policy, policy_sha256 = read_policy(policy_path)
    if expected_policy_sha256 is not None and policy_sha256 != expected_policy_sha256:
        raise BackupSetError("Independent backup policy differs from its approved digest.")
    store = RecoveryStore(policy.destination_identity, timeout=timeout)
    deadline = monotonic() + timeout
    latest: PublicationReceipt | None = None
    for key in store.complete_keys():
        if monotonic() >= deadline:
            raise BackupSetError("Independent backup freshness check exceeded its time limit.")
        receipt = complete_receipt(
            store, key, policy, policy_sha256, key_file=key_file, key_id=key_id
        )
        if latest is None or receipt.snapshot_at_utc > latest.snapshot_at_utc:
            latest = receipt
    if monotonic() >= deadline:
        raise BackupSetError("Independent backup freshness check exceeded its time limit.")
    if latest is None:
        raise BackupSetError("No authenticated independent backup set is complete.")
    return latest


def read_latest_scheduled_attempt(
    policy_path: Path,
    *,
    key_file: Path,
    key_id: str,
    timeout: float = 60,
    expected_policy_sha256: str | None = None,
) -> ScheduledAttemptReceipt:
    """Read the latest attempt status separately from the last verified recovery point."""
    policy, policy_sha256 = read_policy(policy_path)
    if expected_policy_sha256 is not None and policy_sha256 != expected_policy_sha256:
        raise BackupSetError("Independent backup policy differs from its approved digest.")
    store = RecoveryStore(policy.destination_identity, timeout=timeout)
    deadline = monotonic() + timeout
    raw = store.read(store.scheduled_attempt_key, MAX_SCHEDULED_ATTEMPT_BYTES)
    if monotonic() >= deadline:
        raise BackupSetError("Scheduled backup attempt check exceeded its time limit.")
    if raw is None:
        raise BackupSetError("Independent scheduled backup attempt receipt is missing.")
    receipt = verify_scheduled_attempt(raw, key_file=key_file, key_id=key_id)
    if (
        receipt.source_environment != policy.source_environment
        or receipt.policy_revision != policy.revision
        or receipt.policy_sha256 != policy_sha256
    ):
        raise BackupSetError("Scheduled backup attempt does not match the approved scope.")
    return receipt
