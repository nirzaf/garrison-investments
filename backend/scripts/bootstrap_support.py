"""Issue private registration invitations for the approved first two custodians."""

import argparse
import asyncio
import hashlib
import json
import os
import re
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from hmac import compare_digest
from pathlib import Path
from typing import Literal, TextIO
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, SecretStr, model_validator

from app.config import get_settings
from app.database import AsyncSessionLocal, engine
from app.models.support_registration import SupportBootstrap
from app.services.support_bootstrap import BOOTSTRAP_ID, issue_first_custodian_invitations

_MAX_APPROVAL_BYTES = 16_384


class ApprovedCustodian(BaseModel):
    model_config = ConfigDict(extra="forbid")
    person_reference: UUID
    mailbox: EmailStr


class CustodyApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1]
    purpose: Literal["initial_support_custody"]
    preparer_reference: UUID
    reviewer_reference: UUID
    custodians: tuple[ApprovedCustodian, ApprovedCustodian]

    @model_validator(mode="after")
    def ensure_independent(self) -> "CustodyApproval":
        first, second = self.custodians
        if (
            first.person_reference == second.person_reference
            or first.mailbox.casefold() == second.mailbox.casefold()
            or self.preparer_reference == self.reviewer_reference
            or self.reviewer_reference in {first.person_reference, second.person_reference}
        ):
            raise ValueError("The custodians and independent reviewer must be distinct.")
        return self


def read_approval(path: Path, expected_digest: SecretStr) -> tuple[CustodyApproval, str]:
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as handle:
        info = os.fstat(handle.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_mode & 0o077
            or not 0 < info.st_size <= _MAX_APPROVAL_BYTES
        ):
            raise ValueError("Use a private, owned, bounded approval file.")
        body = handle.read(_MAX_APPROVAL_BYTES + 1)
    digest = hashlib.sha256(body).hexdigest()
    expected = expected_digest.get_secret_value().lower()
    if (
        len(body) > _MAX_APPROVAL_BYTES
        or not re.fullmatch(r"[0-9a-f]{64}", expected)
        or not compare_digest(expected, digest)
    ):
        raise ValueError("The approved custody record digest did not match.")
    try:
        approval = CustodyApproval.model_validate_json(body)
    except ValueError:
        raise ValueError("The approved custody record is invalid.") from None
    return approval, digest


@contextmanager
def private_output(destination: Path) -> Iterator[tuple[TextIO, int]]:
    directory_fd = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        directory = os.fstat(directory_fd)
        if directory.st_uid != os.geteuid() or directory.st_mode & 0o077:
            raise ValueError("Custody output requires a private, owned directory.")
        output = os.open(
            destination.name,
            os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_WRONLY,
            0o600,
            dir_fd=directory_fd,
        )
        try:
            with os.fdopen(output, "w", encoding="utf-8") as handle:
                yield handle, directory_fd
        except BaseException:
            os.unlink(destination.name, dir_fd=directory_fd)
            raise
    finally:
        os.close(directory_fd)


def sync_output(handle: TextIO, directory_fd: int) -> None:
    handle.flush()
    os.fsync(handle.fileno())
    os.fsync(directory_fd)


async def issue(
    approval: CustodyApproval, digest: str, destination: Path, *, reissue: bool
) -> None:
    if get_settings().app_env not in {"production", "test"}:
        raise ValueError("Use the isolated test environment or the reviewed production host.")
    with private_output(destination) as (handle, directory_fd):
        async with AsyncSessionLocal() as session:
            result = await issue_first_custodian_invitations(
                session, approval_digest=digest, reissue=reissue
            )
            json.dump(
                [
                    {
                        "person_reference": str(custodian.person_reference),
                        "mailbox": custodian.mailbox,
                        "operator_reference": str(operator),
                        "invitations": invitations,
                    }
                    for custodian, (operator, invitations) in zip(
                        approval.custodians, result.items(), strict=True
                    )
                ],
                handle,
            )
            handle.write("\n")
            sync_output(handle, directory_fd)
            await session.commit()


async def approved_otp_bindings(approval: CustodyApproval, digest: str) -> dict[UUID, str]:
    async with AsyncSessionLocal() as session:
        bootstrap = await session.get(SupportBootstrap, BOOTSTRAP_ID)
        if bootstrap is None or not compare_digest(bootstrap.approval_digest, digest):
            raise ValueError("The approved custody record does not match the issued registry.")
        return {
            reference: custodian.mailbox
            for reference, custodian in zip(
                (bootstrap.first_id, bootstrap.second_id), approval.custodians, strict=True
            )
        }


def write_otp_config(path: Path, bindings: dict[UUID, str]) -> None:
    # Keep the JSON literal intact across dotenv interpolation and its single quotes.
    payload = json.dumps({str(reference): address for reference, address in bindings.items()})
    payload = payload.replace("$", r"\u0024").replace("'", r"\u0027")
    with private_output(path) as (handle, directory_fd):
        handle.write(f"SUPPORT_EMAIL_OTP_RECIPIENTS='{payload}'\n")
        sync_output(handle, directory_fd)


def verify_otp_config(bindings: dict[UUID, str]) -> None:
    settings = get_settings()
    key = settings.support_email_otp_key
    if key is None or len(key.get_secret_value().strip().encode()) < 32:
        raise ValueError("The runtime has no usable support email OTP key.")
    if any(
        settings.support_email_otp_recipients.get(reference) != mailbox
        for reference, mailbox in bindings.items()
    ):
        raise ValueError("Runtime OTP bindings do not match the approved custodians.")


async def apply(args: argparse.Namespace) -> None:
    approval, digest = read_approval(args.approval, SecretStr(args.approval_sha256))
    try:
        settings = get_settings()
        if settings.app_env not in {"production", "test"}:
            raise ValueError("Use the isolated test environment or the reviewed production host.")
        if args.apply:
            await issue(approval, digest, args.output, reissue=args.reissue)
        else:
            bindings = await approved_otp_bindings(approval, digest)
            if args.write_otp_config:
                write_otp_config(args.write_otp_config, bindings)
            else:
                verify_otp_config(bindings)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approval", type=Path, required=True)
    parser.add_argument("--approval-sha256", required=True)
    parser.add_argument("--output", type=Path)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--apply", action="store_true")
    modes.add_argument("--write-otp-config", type=Path)
    modes.add_argument("--verify-otp-config", action="store_true")
    parser.add_argument("--reissue", action="store_true")
    args = parser.parse_args()
    try:
        if not (args.apply or args.write_otp_config or args.verify_otp_config):
            read_approval(args.approval, SecretStr(args.approval_sha256))
            print("Verified the private approval record for two distinct custodians.")
            return
        if args.apply and args.output is None:
            parser.error("--apply requires --output in a private directory")
        asyncio.run(apply(args))
    except (ValueError, OSError) as error:
        parser.exit(1, f"Initial custody enrollment failed: {error}\n")
    if args.apply:
        print("Private invitation file written.")
    elif args.write_otp_config:
        print("Private OTP mailbox configuration written.")
    else:
        print("Runtime OTP bindings match the approved custody record.")


if __name__ == "__main__":
    main()
