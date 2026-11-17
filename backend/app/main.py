from contextlib import asynccontextmanager
from time import perf_counter
from uuid import uuid4

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.config import get_settings
from app.database import AsyncSessionLocal, check_database
from app.middleware import AuthRateLimiter, audit_authenticated_request
from app.observability import bind_log_context, clear_log_context, configure_logging
from app.services.audit_service import AuditService
from app.services.exception_reporter import report_unhandled_exception
from app.utils.exceptions import AppException, ValidationErrorResponse, ValidationIssue
from app.utils.redaction import redact_text
from app.utils.request import get_client_ip, trusted_correlation_ids
from app.utils.security import validate_signing_keys

logger = structlog.get_logger("app.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    # Fail closed before serving: a hardened deployment must never fall back to the
    # published development key pair.
    validate_signing_keys()
    if settings.otp_hardened_env and settings.dev_expose_otp:
        logger.warning(
            "dev_otp_flag_ignored",
            event_type="system_event",
            app_env=settings.app_env,
            comments="DEV_EXPOSE_OTP is ignored in production and staging.",
        )
    if settings.app_env.lower() == "production" and settings.staging_login_otp:
        logger.warning(
            "staging_login_otp_ignored",
            event_type="system_event",
            app_env=settings.app_env,
            comments="STAGING_LOGIN_OTP is ignored outside staging.",
        )
    logger.info(
        "application_starting",
        app_name=app.title,
        event_type="system_event",
        source_service=settings.log_source_service,
        instance_id=settings.log_instance_id,
    )
    async with AsyncSessionLocal() as session:
        await AuditService(session).record(
            action="system.startup",
            event_type="system_event",
            severity="INFO",
            comments="Application starting",
            source_service=settings.log_source_service,
            instance_id=settings.log_instance_id,
        )
        await session.commit()
    yield
    logger.info(
        "application_stopping",
        app_name=app.title,
        event_type="system_event",
        source_service=settings.log_source_service,
        instance_id=settings.log_instance_id,
    )
    async with AsyncSessionLocal() as session:
        await AuditService(session).record(
            action="system.shutdown",
            event_type="system_event",
            severity="INFO",
            comments="Application stopping",
            source_service=settings.log_source_service,
            instance_id=settings.log_instance_id,
        )
        await session.commit()


def create_app() -> FastAPI:
    settings = get_settings()
    # API imports can load Celery modules in-process before application creation.
    # Re-apply the API identity so backend records are never mislabeled as worker records.
    configure_logging(settings, source_service=settings.log_source_service, force=True)
    auth_rate_limiter = AuthRateLimiter(
        redis_url=settings.redis_url,
        window_seconds=settings.auth_rate_limit_window_seconds,
        max_requests=settings.auth_rate_limit_max_requests,
    )
    app = FastAPI(
        title=settings.app_name,
        debug=settings.debug,
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Total-Count", "X-Report-Revision", "X-HR-Case-Review"],
    )

    async def request_context_middleware(request: Request, call_next):
        request_id, session_id = trusted_correlation_ids(request, settings.trusted_proxy_ips_list)
        request_id = request_id or str(uuid4())
        session_id = session_id or request_id
        request.state.request_id = request_id
        request.state.session_id = session_id
        bind_log_context(
            request_id=request_id,
            session_id=session_id,
            ip_address=get_client_ip(request),
            endpoint=request.url.path,
            method=request.method,
            source_service=settings.log_source_service,
            instance_id=settings.log_instance_id,
            cli_session_id=request.headers.get("X-Log-CLI-Session"),
        )
        start = perf_counter()

        def log_completion(status_code: int) -> float:
            duration = perf_counter() - start
            if settings.log_healthchecks or request.url.path not in {
                "/health",
                "/health/readiness",
            }:
                # Included routers keep the original relative route in scope["route"].
                # The effective route includes prefixes and preserves path parameters.
                route = request.scope.get("fastapi", {}).get("effective_route_context")
                route = route or request.scope.get("route")
                logger.info(
                    "http_request_completed",
                    event_type="api_request",
                    method=request.method,
                    route=getattr(route, "path", request.url.path),
                    status_code=status_code,
                    duration_ms=round(duration * 1000, 2),
                )
            return duration

        try:
            response = await call_next(request)
        except Exception:
            log_completion(500)
            raise
        else:
            duration = log_completion(response.status_code)
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Session-ID"] = session_id
            response.headers["X-Process-Time"] = f"{duration:.6f}"
            if request.url.path.startswith(f"{settings.api_v1_prefix}/support/"):
                response.headers["Cache-Control"] = "no-store"
            return response
        finally:
            clear_log_context()

    @app.middleware("http")
    async def auth_rate_limit_middleware(request: Request, call_next):
        if not auth_rate_limiter.applies_to(request):
            return await call_next(request)

        is_limited, remaining = await auth_rate_limiter.check(request)
        headers = {
            "X-RateLimit-Limit": str(settings.auth_rate_limit_max_requests),
            "X-RateLimit-Remaining": str(remaining),
        }
        if is_limited:
            headers["Retry-After"] = str(settings.auth_rate_limit_window_seconds)
            return JSONResponse(
                status_code=429,
                headers=headers,
                content={
                    "detail": "Too many authentication requests. Please try again later.",
                    "error_code": "RATE_LIMITED",
                    "errors": [],
                },
            )

        response = await call_next(request)
        response.headers.update(headers)
        return response

    @app.middleware("http")
    async def audit_request_middleware(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith(f"{get_settings().api_v1_prefix}/hr/"):
            response.headers["Cache-Control"] = "no-store"
        await audit_authenticated_request(request, response)
        return response

    # Register last so correlation and completion surround rate limiting and audit logging.
    app.middleware("http")(request_context_middleware)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        issues = [
            ValidationIssue(
                loc=list(issue["loc"]), msg=redact_text(issue["msg"]), type=issue["type"]
            )
            for issue in exc.errors()
        ]
        response = ValidationErrorResponse(
            detail="One or more request fields are invalid.",
            error_code="VALIDATION_ERROR",
            errors=issues,
        )
        return JSONResponse(status_code=422, content=response.model_dump(mode="json"))

    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
        logger.warning(
            "handled_application_exception",
            event_type="error",
            severity="WARNING" if exc.status_code < 500 else "ERROR",
            request_id=getattr(request.state, "request_id", None),
            session_id=getattr(request.state, "session_id", None),
            method=request.method,
            path=request.url.path,
            error_code=exc.error_code,
            detail=exc.message,
        )
        try:
            async with AsyncSessionLocal() as session:
                await AuditService(session).record(
                    action="http.app_exception",
                    event_type="error",
                    severity="WARNING" if exc.status_code < 500 else "ERROR",
                    entity_type="request",
                    endpoint=request.url.path,
                    http_method=request.method,
                    status_code=exc.status_code,
                    comments=exc.message,
                    context_payload={
                        "error_code": exc.error_code,
                        "errors": exc.errors,
                    },
                )
                await session.commit()
        except Exception:
            logger.warning(
                "app_exception_log_persist_failed",
                request_id=getattr(request.state, "request_id", None),
                path=request.url.path,
                error_code=exc.error_code,
            )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "detail": exc.message,
                "error_code": exc.error_code,
                "errors": exc.errors,
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "unhandled_request_exception",
            event_type="error",
            severity="ERROR",
            request_id=getattr(request.state, "request_id", None),
            session_id=getattr(request.state, "session_id", None),
            method=request.method,
            path=request.url.path,
            exception_type=type(exc).__name__,
            exception_message=str(exc),
            exc_info=exc,
        )
        try:
            async with AsyncSessionLocal() as session:
                await AuditService(session).record(
                    action="http.unhandled_exception",
                    event_type="error",
                    severity="ERROR",
                    entity_type="request",
                    endpoint=request.url.path,
                    http_method=request.method,
                    status_code=500,
                    comments=str(exc),
                    context_payload={
                        "exception_type": type(exc).__name__,
                    },
                )
                await session.commit()
        except Exception:
            logger.warning(
                "unhandled_exception_log_persist_failed",
                request_id=getattr(request.state, "request_id", None),
                path=request.url.path,
                exception_type=type(exc).__name__,
            )
        await report_unhandled_exception(request, exc)
        headers = {}
        if request_id := getattr(request.state, "request_id", None):
            headers["X-Request-ID"] = request_id
        if session_id := getattr(request.state, "session_id", None):
            headers["X-Session-ID"] = session_id
        return JSONResponse(
            status_code=500,
            headers=headers,
            content={
                "detail": "Internal server error.",
                "error_code": "INTERNAL_SERVER_ERROR",
                "errors": [],
            },
        )

    @app.get("/health", tags=["Health"])
    async def health() -> dict[str, str]:
        database_status = "connected" if await check_database() else "unavailable"
        return {
            "status": "ok" if database_status == "connected" else "degraded",
            "database": database_status,
            "redis": "not_checked",
        }

    @app.get("/health/readiness", tags=["Health"])
    async def readiness() -> JSONResponse:
        database_ready = await check_database()
        status_code = 200 if database_ready else 503
        return JSONResponse(
            status_code=status_code,
            content={
                "status": "ready" if database_ready else "not_ready",
                "database": "connected" if database_ready else "unavailable",
            },
        )

    app.include_router(api_router, prefix=settings.api_v1_prefix)
    return app


app = create_app()
