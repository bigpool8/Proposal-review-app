from functools import lru_cache

from supabase import Client, create_client

from app.core.config import settings


@lru_cache(maxsize=1)
def _get_supabase_singleton() -> Client:
    # Cached so the underlying httpx.Client connection pool is reused across
    # requests instead of opening a fresh TCP/TLS connection per call.
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)


def get_supabase() -> Client:
    return _get_supabase_singleton()
