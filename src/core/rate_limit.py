"""Per-API-key rate limiting backed by Redis.

Uses a fixed window counter: tracks how many requests a key has made
in the current time window. Exceeding the limit returns HTTP 429.

Limits (configurable via env):
- Retrieval endpoint: 60 requests/minute per key (AI tools calling frequently)
- Upload endpoint:    20 requests/minute per key (batch uploads are slower)
"""

import time

import redis.asyncio as aioredis
from fastapi import HTTPException, status

from src.core.config import settings


_redis_client: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


async def check_rate_limit(api_key: str, action: str, limit: int, window_seconds: int = 60) -> None:
    """Increment the request counter for this key+action. Raise 429 if over limit.

    Key format: rl:{action}:{key_hash_prefix}:{window}
    Uses a simple fixed-window counter with Redis INCR + EXPIRE.
    """
    redis = get_redis()
    window = int(time.time()) // window_seconds
    # Use only the first 16 chars of the key to avoid storing full secrets in Redis
    key_prefix = api_key[:16] if len(api_key) >= 16 else api_key
    redis_key = f"rl:{action}:{key_prefix}:{window}"

    try:
        count = await redis.incr(redis_key)
        if count == 1:
            # First request in this window — set TTL so keys auto-expire
            await redis.expire(redis_key, window_seconds * 2)
        if count > limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded: {limit} {action} requests per {window_seconds}s. Try again shortly.",
                headers={"Retry-After": str(window_seconds)},
            )
    except HTTPException:
        raise
    except Exception:
        # Redis unavailable — fail open (don't block requests if Redis is down)
        pass
