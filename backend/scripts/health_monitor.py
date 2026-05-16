from __future__ import annotations

import argparse
import os
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class HealthCheckResult:
    url: str
    ok: bool
    status: int | None
    body_preview: str


def check_url(url: str, timeout: int) -> HealthCheckResult:
    request = Request(url, headers={"User-Agent": "garrison-health-monitor/1.0"})
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read(800).decode("utf-8", errors="replace")
            return HealthCheckResult(
                url=url,
                ok=200 <= response.status < 300,
                status=response.status,
                body_preview=body,
            )
    except HTTPError as exc:
        return HealthCheckResult(
            url=url,
            ok=False,
            status=exc.code,
            body_preview=exc.read(800).decode("utf-8", errors="replace"),
        )
    except URLError as exc:
        return HealthCheckResult(url=url, ok=False, status=None, body_preview=str(exc.reason))


def send_alert(
    *,
    smtp_host: str,
    smtp_port: int,
    from_email: str,
    recipients: list[str],
    result: HealthCheckResult,
) -> None:
    if not recipients:
        return
    message = EmailMessage()
    message["From"] = from_email
    message["To"] = ", ".join(recipients)
    message["Subject"] = f"Garrisons portal health check failed: {result.url}"
    message.set_content(
        "\n".join(
            [
                "The construction portal health monitor detected a failed check.",
                f"URL: {result.url}",
                f"Status: {result.status or 'unreachable'}",
                "",
                "Response preview:",
                result.body_preview,
            ]
        )
    )
    with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as smtp:
        smtp.send_message(message)


def parse_recipients(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run uptime checks and email alerts on failure.")
    parser.add_argument("--url", action="append", required=True)
    parser.add_argument("--timeout", type=int, default=10)
    parser.add_argument("--smtp-host", default=os.getenv("SMTP_HOST", "localhost"))
    parser.add_argument("--smtp-port", type=int, default=int(os.getenv("SMTP_PORT", "1025")))
    parser.add_argument(
        "--from-email",
        default=os.getenv("SMTP_FROM_EMAIL", "no-reply@garrisons.qa"),
    )
    parser.add_argument("--alert-to", default=os.getenv("MONITOR_ALERT_RECIPIENTS", ""))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    recipients = parse_recipients(args.alert_to)
    failed: list[HealthCheckResult] = []
    for url in args.url:
        result = check_url(url, args.timeout)
        state = "ok" if result.ok else "failed"
        print(f"{url} {state} status={result.status or 'unreachable'}")
        if result.ok:
            continue
        failed.append(result)
        send_alert(
            smtp_host=args.smtp_host,
            smtp_port=args.smtp_port,
            from_email=args.from_email,
            recipients=recipients,
            result=result,
        )
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
