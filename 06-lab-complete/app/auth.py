"""Reject missing/empty secrets and compare in constant time."""
import secrets
from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader
from .config import settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

def verify_api_key(api_key: str | None = Security(api_key_header)) -> str:
    if not api_key or not settings.agent_api_key or not secrets.compare_digest(
        api_key.encode(), settings.agent_api_key.encode()
    ):
        raise HTTPException(status_code=401, detail="Missing or invalid API key")
    return api_key

