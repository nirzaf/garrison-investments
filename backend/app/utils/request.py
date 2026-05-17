from fastapi import Request

from app.config import get_settings


def get_client_ip(request: Request) -> str | None:
    direct_ip = request.client.host if request.client else None
    settings = get_settings()
    forwarded_for = request.headers.get("X-Forwarded-For")
    if direct_ip and direct_ip in settings.trusted_proxy_ips_list and forwarded_for:
        forwarded_ip = forwarded_for.split(",")[0].strip()
        if forwarded_ip:
            return forwarded_ip
    real_ip = request.headers.get("X-Real-IP")
    if direct_ip and direct_ip in settings.trusted_proxy_ips_list and real_ip:
        forwarded_ip = real_ip.strip()
        if forwarded_ip:
            return forwarded_ip
    return direct_ip