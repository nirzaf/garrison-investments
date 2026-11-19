"""Unenrolled forward097 sequence. No concrete production adapter exists.

All operations below are explicit reviewed operator boundaries; an implementation
must not treat booleans supplied by CI as evidence. Exceptions retain containment.
"""

from typing import Protocol


class MaintenanceBoundary(Protocol):
    def verify_exact_release(self) -> None: ...
    def establish_and_verify_ingress_block(self) -> None: ...
    def stop_and_drain_writers(self) -> None: ...
    def verify_no_writer_sessions(self) -> None: ...
    def verify_source093_and_data(self) -> None: ...
    def consume_exact_permit(self) -> None: ...
    def migrate097(self) -> None: ...
    def verify_schema097(self) -> None: ...
    def start_backend_and_guarded_nginx_only(self) -> None: ...
    def verify_read_only_smoke(self) -> None: ...
    def start_and_verify_workers(self) -> None: ...
    def reopen_business_ingress(self) -> None: ...
    def record_completed_release(self) -> None: ...
    def stop_and_preserve_failure(self) -> None: ...


def exercise_sequence(operator: MaintenanceBoundary) -> None:
    """Called only inside the existing exclusive deployment lock by future adapter.

    No backup requirement in this specific owner exception. No downgrade or old
    image rollback exists. CI/permit/source mismatches must never reach migration.
    """
    operator.verify_exact_release()
    try:
        operator.establish_and_verify_ingress_block()
        operator.stop_and_drain_writers()
        operator.verify_no_writer_sessions()
        operator.verify_source093_and_data()
        operator.verify_exact_release()
        operator.consume_exact_permit()
        operator.migrate097()
        operator.verify_schema097()
        operator.start_backend_and_guarded_nginx_only()
        operator.verify_read_only_smoke()
        operator.start_and_verify_workers()
        operator.reopen_business_ingress()
        operator.record_completed_release()
    except BaseException:
        operator.stop_and_preserve_failure()
        raise
