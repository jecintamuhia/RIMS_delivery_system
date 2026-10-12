"""Application factory.

Everything the process needs is assembled here: configuration, logging, middleware, the error
envelope and the routers. Two deliberate choices are worth stating.

**Exceptions become one shape.** Every failure the client sees is ``{"code", "message",
"details"}``. Unexpected exceptions are logged with a traceback and answered with a generic
message and no detail - an internal error must never leak a stack trace, a SQL string or a file
path to a customer's browser.

**Probes sit outside the version prefix.** ``/health`` and ``/ready`` are mounted at the root
because orchestrators probe fixed paths; everything else lives under ``/api/v1``.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from app.api.auth import router as auth_router
from app.api.health import router as health_router
from app.api.public import router as public_router
from app.config import Settings, get_settings
from app.db.session import dispose_engine, session_scope
from app.errors import STATUS_BY_CODE, AppError, ErrorCode
from app.observability import RequestContextMiddleware, configure_logging, log_event
from app.ratelimit import client_key, enforce
from app.services import bootstrap

logger = logging.getLogger("app.main")

DESCRIPTION = """
Backend for the RIMs delivery cost calculator.

The customer flow is: search for or pin a delivery location, and the server resolves it to a
configured destination, obtains the **actual road distance** from the routing provider, applies
RIMs' configured destination/road/vehicle pricing, and returns the fee.

If any of those steps cannot be completed truthfully the quote is returned with a failure
reason instead of an estimate. Prices are never guessed, and a straight-line distance is never
substituted for a road distance.
""".strip()

TAGS = [
    {"name": "public", "description": "Customer-facing calculator endpoints. No authentication."},
    {"name": "admin", "description": "Staff administration. Session cookie plus CSRF token required."},
    {"name": "auth", "description": "Sign in, sign out and current session."},
    {"name": "health", "description": "Liveness and readiness probes."},
]


def _error_response(code: str, message: str, details: dict[str, object] | None, status: int) -> JSONResponse:
    payload: dict[str, object] = {"code": code, "message": message, "details": details or {}}
    return JSONResponse(status_code=status, content=payload)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        # Deliberate, explainable failures are not logged as errors; they are expected states.
        log_event(
            logger,
            logging.INFO,
            "handled domain error",
            path=request.url.path,
            code=exc.code,
            status=exc.status_code,
        )
        return _error_response(exc.code, exc.message, dict(exc.details), exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Flatten pydantic's error list into ``field -> message`` so the admin forms can show the
        # problem next to the input that caused it.
        fields: dict[str, str] = {}
        for error in exc.errors():
            location = ".".join(str(part) for part in error.get("loc", ()) if part != "body")
            fields.setdefault(location or "request", str(error.get("msg", "invalid value")))
        return _error_response(
            ErrorCode.VALIDATION,
            "Please check the details you entered.",
            {"fields": fields},
            STATUS_BY_CODE[ErrorCode.VALIDATION],
        )

    @app.exception_handler(IntegrityError)
    async def _integrity_error(request: Request, exc: IntegrityError) -> JSONResponse:
        log_event(
            logger,
            logging.WARNING,
            "database constraint violation",
            path=request.url.path,
            constraint=str(getattr(exc, "orig", exc))[:200],
        )
        return _error_response(
            ErrorCode.VALIDATION,
            "That change conflicts with something that already exists.",
            None,
            STATUS_BY_CODE[ErrorCode.VALIDATION],
        )

    @app.exception_handler(SQLAlchemyError)
    async def _database_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        logger.exception("database failure on %s", request.url.path, exc_info=exc)
        return _error_response(
            ErrorCode.SERVER,
            AppError(ErrorCode.SERVER).message,
            None,
            STATUS_BY_CODE[ErrorCode.SERVER],
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = ErrorCode.NOT_FOUND if exc.status_code == 404 else ErrorCode.UNKNOWN
        if exc.status_code == 401:
            code = ErrorCode.SESSION_EXPIRED
        elif exc.status_code == 403:
            code = ErrorCode.FORBIDDEN
        return _error_response(code, str(exc.detail), None, exc.status_code)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "-")
        logger.exception("unhandled error on %s (request_id=%s)", request.url.path, request_id, exc_info=exc)
        return _error_response(
            ErrorCode.SERVER,
            AppError(ErrorCode.SERVER).message,
            # The request id is the one piece of diagnostic information safe to hand back: it
            # lets an operator find the full traceback in the logs.
            {"requestId": request_id},
            STATUS_BY_CODE[ErrorCode.SERVER],
        )


def register_middleware(app: FastAPI, settings: Settings) -> None:
    app.add_middleware(RequestContextMiddleware)

    # CORS with credentials: the admin app runs on a different origin and is cookie-authenticated,
    # so the wildcard origin is never allowed.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-CSRF-Token", "X-Request-ID"],
        expose_headers=["X-Request-ID", "X-CSRF-Token"],
        max_age=600,
    )

    @app.middleware("http")
    async def rate_limit(request: Request, call_next: RequestResponseEndpoint) -> Response:
        decision = enforce(request)
        if decision is not None and not decision.allowed:
            log_event(
                logger,
                logging.WARNING,
                "rate limited",
                path=request.url.path,
                client=client_key(request),
                bucket_limit=decision.limit,
            )
            response = _error_response(
                ErrorCode.NETWORK,
                "Too many requests. Please wait a moment and try again.",
                {"retryAfterSeconds": decision.retry_after},
                429,
            )
            response.headers["Retry-After"] = str(decision.retry_after)
            return response
        result = await call_next(request)
        if decision is not None and decision.limit:
            result.headers["X-RateLimit-Limit"] = str(decision.limit)
            result.headers["X-RateLimit-Remaining"] = str(decision.remaining)
        return result


def register_routes(app: FastAPI, settings: Settings) -> None:
    app.include_router(health_router)
    api = APIRouter(prefix=settings.api_prefix)
    api.include_router(public_router)
    api.include_router(auth_router)
    # Admin routers are registered by app.api.admin (imported here to avoid a circular import).
    from app.api import admin

    api.include_router(admin.router)
    app.include_router(api)

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, object]:
        return {
            "service": settings.app_name,
            "version": "1.0.0",
            "environment": settings.environment,
            "api": settings.api_prefix,
            "docs": "/docs" if settings.docs_enabled else None,
            "health": "/health",
        }


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(
        level="DEBUG" if settings.debug else "INFO",
        json_output=settings.environment not in {"development", "test"},
    )
    logger.info(
        "starting %s in %s", settings.app_name, settings.environment
    )

    async with session_scope() as session:
        await bootstrap.run(session, settings)

    from app.cache import get_cache
    from app.providers import get_providers

    geocoder, routing = get_providers()
    log_event(
        logger,
        logging.INFO,
        "providers resolved",
        geocoding=getattr(geocoder, "name", "?"),
        routing=getattr(routing, "name", "?"),
    )
    await get_cache()

    log_event(logger, logging.INFO, "startup complete")
    try:
        yield
    finally:
        await dispose_engine()
        logger.info("shutdown complete")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title=settings.app_name,
        description=DESCRIPTION,
        version="1.0.0",
        openapi_url=f"{settings.api_prefix}/openapi.json" if settings.docs_enabled else None,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url="/redoc" if settings.docs_enabled else None,
        openapi_tags=TAGS,
        lifespan=lifespan,
    )
    register_exception_handlers(app)
    register_middleware(app, settings)
    register_routes(app, settings)
    return app


app = create_app()
