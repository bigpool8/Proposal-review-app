import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from jose import JWTError, jwt

from app.core.config import settings


def validate_password(password: str) -> bool:
    # bcrypt는 72바이트를 넘는 비밀번호를 조용히 자르지 않고 예외를 던지므로 상한도 검사한다.
    return (
        6 <= len(password.encode()) <= 72
        and bool(re.search(r"[A-Za-z]", password))
        and bool(re.search(r"\d", password))
    )


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except ValueError:
        # 72바이트 초과 등 bcrypt가 거부하는 입력 — 인증 실패로 처리
        return False


def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(hours=settings.ACCESS_TOKEN_EXPIRE_HOURS)
    )
    to_encode["exp"] = expire
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        return None
