import time
import secrets
from collections import defaultdict
from fastapi import Header, Query, HTTPException, Depends, Request
from sqlalchemy.orm import Session
from app.database import get_db, ApiKey, UsageLog

_RATE_BUCKETS = defaultdict(list)

PLAN_LIMITS = {
    "free": {"rpm": 30, "quota": 10000, "price_inr": 0},
    "pro": {"rpm": 300, "quota": 250000, "price_inr": 999},
    "enterprise": {"rpm": 2000, "quota": 5000000, "price_inr": 4999},
}


def generate_zoy_api_key() -> str:
    return f"zoy_live_{secrets.token_hex(20)}"


def verify_api_key(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    key: str | None = Query(default=None, description="Zoy Maps API Key"),
    db: Session = Depends(get_db),
) -> ApiKey:
    raw_key = x_api_key or key
    if not raw_key:
        raise HTTPException(
            status_code=401,
            detail={
                "error": "MISSING_API_KEY",
                "message": "Provide your Zoy Maps API key via 'X-API-Key' header or '?key=' query parameter.",
            },
        )

    api_key_obj = db.query(ApiKey).filter(ApiKey.key == raw_key).first()
    if not api_key_obj:
        raise HTTPException(
            status_code=403,
            detail={"error": "INVALID_API_KEY", "message": "The provided Zoy Maps API key does not exist."},
        )

    if not api_key_obj.is_active:
        raise HTTPException(
            status_code=403,
            detail={"error": "REVOKED_API_KEY", "message": "This API key has been deactivated."},
        )

    if api_key_obj.requests_used >= api_key_obj.monthly_quota:
        raise HTTPException(
            status_code=429,
            detail={"error": "QUOTA_EXCEEDED", "message": "Monthly API request quota exceeded. Upgrade plan in Console."},
        )

    now = time.time()
    bucket = _RATE_BUCKETS[raw_key]
    _RATE_BUCKETS[raw_key] = [ts for ts in bucket if now - ts < 60.0]

    if len(_RATE_BUCKETS[raw_key]) >= api_key_obj.rate_limit_per_min:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "RATE_LIMIT_EXCEEDED",
                "message": f"Rate limit of {api_key_obj.rate_limit_per_min} requests/minute exceeded.",
            },
        )

    _RATE_BUCKETS[raw_key].append(now)
    return api_key_obj


def record_usage(
    db: Session,
    api_key_obj: ApiKey,
    endpoint: str,
    latency_ms: float,
    query_summary: str = "",
    method: str = "GET",
    status_code: int = 200,
):
    api_key_obj.requests_used += 1
    log = UsageLog(
        api_key_id=api_key_obj.id,
        endpoint=endpoint,
        method=method,
        status_code=status_code,
        latency_ms=round(latency_ms, 2),
        query_summary=query_summary[:250],
    )
    db.add(log)
    db.commit()
