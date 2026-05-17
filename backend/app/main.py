from contextlib import asynccontextmanager
from time import perf_counter
from uuid import uuid4

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.config import get_settings
from app.database import check_database
from app.middleware import AuthRateLimiter, audit_authenticated_request
from app.services.exception_reporter import report_unhandled_exception
from app.utils.exceptions import AppException

logger = structlog.get_logger("app.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("application_starting", app_name=app.title)
    yield
    logger.info("application_stopping", app_name=app.title)


def create_app() -> FastAPI:
    settings = get_settings()
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
    )

    @app.middleware("http")
    async def request_context_middleware(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid4()))
        request.state.request_id = request_id
        start = perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time"] = f"{perf_counter() - start:.6f}"
        return response

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
        await audit_authenticated_request(request, response)
        return response

    @app.exception_handler(AppException)
    async def app_exception_handler(_: Request, exc: AppException) -> JSONResponse:
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
            request_id=getattr(request.state, "request_id", None),
            method=request.method,
            path=request.url.path,
            exception_type=type(exc).__name__,
            exception_message=str(exc),
        )
        await report_unhandled_exception(request, exc)
        return JSONResponse(
            status_code=500,
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
