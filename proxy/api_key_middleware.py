"""
FastAPI middleware for API key validation.

Security features:
- Validates API key header on all /v1/ endpoints
- Uses timing-safe comparison via APIKeyStorage
- Logs failed validation attempts (with partial key only)
- Allows bypass for health/status endpoints
"""
import logging
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from utils.api_key_storage import APIKeyStorage

logger = logging.getLogger(__name__)

# Endpoints that don't require API key authentication
EXEMPT_PATHS = {
    "/",
    "/health",
    "/healthz",
    "/auth/status",
    "/docs",
    "/openapi.json",
    "/redoc",
}

# Path prefixes that don't require API key authentication
EXEMPT_PREFIXES = (
    "/ui/",              # Web UI static files (auth handled by frontend)
)

# Management API paths that don't require authentication (OAuth callbacks)
MANAGEMENT_EXEMPT_PATHS = {
    "/api/management/auth/claude/callback",
    "/api/management/auth/claude/callback-long-term",
    "/api/management/auth/chatgpt/callback",
}


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Middleware to validate API keys on incoming requests"""

    def __init__(self, app):
        super().__init__(app)
        self.storage = APIKeyStorage()

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Skip exempt paths
        if path in EXEMPT_PATHS:
            return await call_next(request)

        # Skip exempt prefixes (web UI static files)
        if path.startswith(EXEMPT_PREFIXES):
            return await call_next(request)

        # Skip management OAuth callback paths (these need to work without auth)
        if path in MANAGEMENT_EXEMPT_PATHS:
            return await call_next(request)

        # Validate management API endpoints with API key
        if path.startswith("/api/management/"):
            return await self._validate_management_request(request, call_next)

        # Only validate /v1/ API endpoints
        if not path.startswith("/v1/"):
            return await call_next(request)

        # Extract API key from headers
        api_key = self._extract_api_key(request)

        if not api_key:
            logger.warning(f"API key validation failed: no key provided for {path}")
            return JSONResponse(
                status_code=401,
                content={
                    "error": {
                        "message": "API key required. Provide Authorization: Bearer <key> or X-API-Key header.",
                        "type": "authentication_error",
                        "code": 401
                    }
                }
            )

        # Validate the key (timing-safe comparison happens in storage)
        key_id = self.storage.validate_key(api_key)
        if not key_id:
            return JSONResponse(
                status_code=401,
                content={
                    "error": {
                        "message": "Invalid API key.",
                        "type": "authentication_error",
                        "code": 401
                    }
                }
            )

        # Store key_id in request state for potential audit logging
        request.state.api_key_id = key_id

        return await call_next(request)

    async def _validate_management_request(self, request: Request, call_next):
        """Validate management API requests with API key"""
        path = request.url.path

        # Extract API key from headers or query params (for OAuth redirects)
        api_key = self._extract_api_key(request)

        if not api_key:
            logger.warning(f"Management API key validation failed: no key provided for {path}")
            return JSONResponse(
                status_code=401,
                content={
                    "error": {
                        "message": "API key required for management API. Provide Authorization: Bearer <key> or X-API-Key header.",
                        "type": "authentication_error",
                        "code": 401
                    }
                }
            )

        # Validate the key
        key_id = self.storage.validate_key(api_key)
        if not key_id:
            return JSONResponse(
                status_code=401,
                content={
                    "error": {
                        "message": "Invalid API key.",
                        "type": "authentication_error",
                        "code": 401
                    }
                }
            )

        # Store key_id in request state
        request.state.api_key_id = key_id
        return await call_next(request)

    def _extract_api_key(self, request: Request) -> str | None:
        """Extract API key from request headers"""
        # Get auth-related headers
        auth_header = request.headers.get("Authorization", "")
        x_api_key = request.headers.get("X-API-Key") or request.headers.get("x-api-key")

        # Debug: log what headers we received (truncated for security)
        if auth_header:
            logger.debug(f"Authorization header: {auth_header[:30]}...")
        if x_api_key:
            logger.debug(f"X-API-Key header: {x_api_key[:20]}...")
        if not auth_header and not x_api_key:
            logger.debug(f"No auth headers found. All headers: {list(request.headers.keys())}")

        # Check Authorization header first (Bearer token format)
        if auth_header.lower().startswith("bearer "):
            potential_key = auth_header[7:]  # Remove "Bearer " prefix
            # Only use if it looks like our key format
            if potential_key.startswith("llmux-"):
                return potential_key
            else:
                logger.debug(f"Bearer token doesn't start with 'llmux-': {potential_key[:15]}...")

        # Check X-API-Key header as alternative
        if x_api_key:
            if x_api_key.startswith("llmux-"):
                return x_api_key
            else:
                logger.debug(f"X-API-Key doesn't start with 'llmux-': {x_api_key[:15]}...")

        return None
