"""
Management API endpoints for Web UI.

Provides endpoints for:
- Server control (status, start, stop)
- Authentication management (Claude and ChatGPT OAuth)
- API key management (CRUD operations)
"""
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from utils.api_key_storage import APIKeyStorage
from utils.storage import TokenStorage
from chatgpt_oauth.storage import ChatGPTTokenStorage
from chatgpt_oauth.token_manager import ChatGPTOAuthManager
from oauth.pkce import PKCEManager
from oauth.authorization import AuthorizationURLBuilder
from oauth.token_exchange import exchange_code, exchange_code_for_long_term_token
from oauth.token_refresh import refresh_tokens
from chatgpt_oauth.pkce import PKCEManager as ChatGPTPKCEManager
from chatgpt_oauth.authorization import AuthorizationURLBuilder as ChatGPTAuthorizationURLBuilder
from chatgpt_oauth.token_exchange import exchange_code_for_tokens

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/management", tags=["management"])

# Global server state tracking
_server_start_time: Optional[float] = None


def set_server_start_time():
    """Called when server starts to track uptime"""
    global _server_start_time
    _server_start_time = time.time()


# Initialize start time when module loads (server is starting)
set_server_start_time()


# ============================================================================
# Request/Response Models
# ============================================================================

class ServerStatusResponse(BaseModel):
    running: bool
    bind_address: str
    port: int
    uptime_seconds: Optional[float] = None
    uptime_formatted: Optional[str] = None


class AuthStatusResponse(BaseModel):
    has_tokens: bool
    is_expired: bool
    expires_at: Optional[str] = None
    time_until_expiry: Optional[str] = None
    token_type: Optional[str] = None
    account_id: Optional[str] = None  # ChatGPT only


class AuthLoginResponse(BaseModel):
    auth_url: str
    state: str


class CreateKeyRequest(BaseModel):
    name: str


class CreateKeyResponse(BaseModel):
    id: str
    name: str
    key: str  # Plaintext key - shown only once
    key_prefix: str
    created_at: str


class RenameKeyRequest(BaseModel):
    name: str


class APIKeyResponse(BaseModel):
    id: str
    name: str
    key_prefix: str
    created_at: str
    last_used_at: Optional[str] = None
    usage_count: int


class MessageResponse(BaseModel):
    message: str
    success: bool = True


# ============================================================================
# Server Control Endpoints
# ============================================================================

@router.get("/server/status", response_model=ServerStatusResponse)
async def get_server_status():
    """Get current server status"""
    from settings import PORT, BIND_ADDRESS

    uptime_seconds = None
    uptime_formatted = None

    if _server_start_time:
        uptime_seconds = time.time() - _server_start_time
        # Format uptime
        hours = int(uptime_seconds // 3600)
        minutes = int((uptime_seconds % 3600) // 60)
        seconds = int(uptime_seconds % 60)

        if hours > 0:
            uptime_formatted = f"{hours}h {minutes}m {seconds}s"
        elif minutes > 0:
            uptime_formatted = f"{minutes}m {seconds}s"
        else:
            uptime_formatted = f"{seconds}s"

    return ServerStatusResponse(
        running=True,  # If this endpoint responds, server is running
        bind_address=BIND_ADDRESS,
        port=PORT,
        uptime_seconds=uptime_seconds,
        uptime_formatted=uptime_formatted
    )


# ============================================================================
# Claude Authentication Endpoints
# ============================================================================

@router.get("/auth/claude/status", response_model=AuthStatusResponse)
async def get_claude_auth_status():
    """Get Claude OAuth token status"""
    storage = TokenStorage()
    status = storage.get_status()

    return AuthStatusResponse(
        has_tokens=status.get("has_tokens", False),
        is_expired=status.get("is_expired", True),
        expires_at=status.get("expires_at"),
        time_until_expiry=status.get("time_until_expiry"),
        token_type=status.get("token_type")
    )


@router.get("/auth/claude/login", response_model=AuthLoginResponse)
async def start_claude_login():
    """Start Claude OAuth login flow - returns auth URL for redirect"""
    pkce = PKCEManager()
    auth_builder = AuthorizationURLBuilder(pkce)
    auth_url = auth_builder.get_authorize_url()

    return AuthLoginResponse(
        auth_url=auth_url,
        state=pkce.state
    )


@router.get("/auth/claude/callback")
async def claude_oauth_callback(
    code: str = Query(..., description="Authorization code from OAuth"),
    state: Optional[str] = Query(None, description="State parameter")
):
    """Handle Claude OAuth callback - exchanges code for tokens"""
    try:
        storage = TokenStorage()
        pkce = PKCEManager()

        # Combine code and state if state provided
        full_code = f"{code}#{state}" if state else code

        result = await exchange_code(full_code, storage, pkce)

        # Redirect to UI with success
        return RedirectResponse(url="/ui/auth?success=true&provider=claude")
    except Exception as e:
        logger.error(f"Claude OAuth callback failed: {e}")
        return RedirectResponse(url=f"/ui/auth?error={str(e)}&provider=claude")


@router.post("/auth/claude/refresh", response_model=MessageResponse)
async def refresh_claude_tokens():
    """Refresh Claude OAuth tokens"""
    storage = TokenStorage()

    if storage.is_long_term_token():
        raise HTTPException(
            status_code=400,
            detail="Long-term tokens cannot be refreshed. Please re-authenticate."
        )

    success = await refresh_tokens(storage)

    if success:
        return MessageResponse(message="Tokens refreshed successfully")
    else:
        raise HTTPException(status_code=500, detail="Failed to refresh tokens")


@router.post("/auth/claude/logout", response_model=MessageResponse)
async def claude_logout():
    """Clear Claude OAuth tokens"""
    storage = TokenStorage()
    storage.clear_tokens()
    return MessageResponse(message="Logged out successfully")


@router.get("/auth/claude/login-long-term", response_model=AuthLoginResponse)
async def start_claude_long_term_login():
    """Start Claude OAuth login flow for long-term token (1 year)"""
    pkce = PKCEManager()
    auth_builder = AuthorizationURLBuilder(pkce)
    auth_url = auth_builder.get_authorize_url_for_long_term_token()

    return AuthLoginResponse(
        auth_url=auth_url,
        state=pkce.state
    )


@router.get("/auth/claude/callback-long-term")
async def claude_long_term_oauth_callback(
    code: str = Query(..., description="Authorization code from OAuth"),
    state: Optional[str] = Query(None, description="State parameter")
):
    """Handle Claude OAuth callback for long-term token"""
    try:
        storage = TokenStorage()
        pkce = PKCEManager()

        # Combine code and state if state provided
        full_code = f"{code}#{state}" if state else code

        result = await exchange_code_for_long_term_token(full_code, storage, pkce)

        # Redirect to UI with success
        return RedirectResponse(url="/ui/auth?success=true&provider=claude&long_term=true")
    except Exception as e:
        logger.error(f"Claude long-term OAuth callback failed: {e}")
        return RedirectResponse(url=f"/ui/auth?error={str(e)}&provider=claude")


# ============================================================================
# ChatGPT Authentication Endpoints
# ============================================================================

@router.get("/auth/chatgpt/status", response_model=AuthStatusResponse)
async def get_chatgpt_auth_status():
    """Get ChatGPT OAuth token status"""
    storage = ChatGPTTokenStorage()
    status = storage.get_status()

    return AuthStatusResponse(
        has_tokens=status.get("has_tokens", False),
        is_expired=status.get("is_expired", True),
        expires_at=status.get("expires_at"),
        time_until_expiry=status.get("time_until_expiry"),
        account_id=status.get("account_id")
    )


@router.get("/auth/chatgpt/login", response_model=AuthLoginResponse)
async def start_chatgpt_login():
    """Start ChatGPT OAuth login flow - returns auth URL for redirect"""
    pkce = ChatGPTPKCEManager()
    auth_builder = ChatGPTAuthorizationURLBuilder(pkce)
    auth_url = auth_builder.get_authorize_url()

    return AuthLoginResponse(
        auth_url=auth_url,
        state=pkce.state
    )


@router.get("/auth/chatgpt/callback")
async def chatgpt_oauth_callback(
    code: str = Query(..., description="Authorization code from OAuth"),
    state: Optional[str] = Query(None, description="State parameter")
):
    """Handle ChatGPT OAuth callback - exchanges code for tokens"""
    try:
        pkce = ChatGPTPKCEManager()
        storage = ChatGPTTokenStorage()

        result = await exchange_code_for_tokens(code, pkce)

        if result:
            # Save tokens to storage
            auth_data = {
                "tokens": {
                    "id_token": result.token_data.id_token,
                    "access_token": result.token_data.access_token,
                    "refresh_token": result.token_data.refresh_token,
                    "account_id": result.token_data.account_id,
                },
                "last_refresh": result.last_refresh
            }
            storage.save_tokens(auth_data)

            return RedirectResponse(url="/ui/auth?success=true&provider=chatgpt")
        else:
            return RedirectResponse(url="/ui/auth?error=Token+exchange+failed&provider=chatgpt")
    except Exception as e:
        logger.error(f"ChatGPT OAuth callback failed: {e}")
        return RedirectResponse(url=f"/ui/auth?error={str(e)}&provider=chatgpt")


@router.post("/auth/chatgpt/refresh", response_model=MessageResponse)
async def refresh_chatgpt_tokens():
    """Refresh ChatGPT OAuth tokens"""
    manager = ChatGPTOAuthManager()
    success = await manager.refresh_tokens()

    if success:
        return MessageResponse(message="Tokens refreshed successfully")
    else:
        raise HTTPException(status_code=500, detail="Failed to refresh tokens")


@router.post("/auth/chatgpt/logout", response_model=MessageResponse)
async def chatgpt_logout():
    """Clear ChatGPT OAuth tokens"""
    storage = ChatGPTTokenStorage()
    storage.clear_tokens()
    return MessageResponse(message="Logged out successfully")


# ============================================================================
# API Key Management Endpoints
# ============================================================================

@router.get("/keys", response_model=list[APIKeyResponse])
async def list_api_keys():
    """List all API keys"""
    storage = APIKeyStorage()
    keys = storage.list_keys()

    return [
        APIKeyResponse(
            id=key["id"],
            name=key["name"],
            key_prefix=key["key_prefix"],
            created_at=key["created_at"],
            last_used_at=key.get("last_used_at"),
            usage_count=key.get("usage_count", 0)
        )
        for key in keys
    ]


@router.post("/keys", response_model=CreateKeyResponse)
async def create_api_key(request: CreateKeyRequest):
    """Create a new API key - returns plaintext key only once"""
    storage = APIKeyStorage()
    key_id, plaintext_key = storage.create_key(request.name)

    # Get full key info
    key_info = storage.get_key_by_id(key_id)

    return CreateKeyResponse(
        id=key_id,
        name=request.name,
        key=plaintext_key,
        key_prefix=key_info["key_prefix"],
        created_at=key_info["created_at"]
    )


@router.delete("/keys/{key_id}", response_model=MessageResponse)
async def delete_api_key(key_id: str):
    """Delete an API key"""
    storage = APIKeyStorage()

    if not storage.get_key_by_id(key_id):
        raise HTTPException(status_code=404, detail="API key not found")

    success = storage.delete_key(key_id)

    if success:
        return MessageResponse(message="API key deleted successfully")
    else:
        raise HTTPException(status_code=500, detail="Failed to delete API key")


@router.patch("/keys/{key_id}", response_model=APIKeyResponse)
async def rename_api_key(key_id: str, request: RenameKeyRequest):
    """Rename an API key"""
    storage = APIKeyStorage()

    if not storage.get_key_by_id(key_id):
        raise HTTPException(status_code=404, detail="API key not found")

    success = storage.rename_key(key_id, request.name)

    if not success:
        raise HTTPException(status_code=500, detail="Failed to rename API key")

    # Get updated key info
    key_info = storage.get_key_by_id(key_id)

    return APIKeyResponse(
        id=key_info["id"],
        name=key_info["name"],
        key_prefix=key_info["key_prefix"],
        created_at=key_info["created_at"],
        last_used_at=key_info.get("last_used_at"),
        usage_count=key_info.get("usage_count", 0)
    )

