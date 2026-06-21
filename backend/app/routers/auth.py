import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from supabase import Client

from app.core.security import (
    create_access_token,
    decode_access_token,
    get_password_hash,
    validate_password,
    verify_password,
)
from app.database import get_supabase
from app.schemas.user import Token, UserCreate, UserResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


@router.post("/register", status_code=201, response_model=UserResponse)
def register(body: UserCreate, sb: Client = Depends(get_supabase)):
    if not validate_password(body.password):
        raise HTTPException(
            status_code=422,
            detail="패스워드는 영문과 숫자를 포함하여 6자 이상이어야 합니다.",
        )
    existing = sb.table("users").select("id").eq("username", body.username).execute()
    if existing.data:
        raise HTTPException(status_code=409, detail="이미 사용 중인 아이디입니다.")

    res = sb.table("users").insert({
        "id": str(uuid.uuid4()),
        "username": body.username,
        "password_hash": get_password_hash(body.password),
    }).execute()
    user = res.data[0]
    return UserResponse(id=user["id"], username=user["username"])


@router.post("/login", response_model=Token)
def login(body: UserCreate, sb: Client = Depends(get_supabase)):
    res = sb.table("users").select("id, username, password_hash").eq("username", body.username).execute()
    if not res.data:
        raise HTTPException(status_code=401, detail="아이디 또는 패스워드가 올바르지 않습니다.")
    user = res.data[0]
    if not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="아이디 또는 패스워드가 올바르지 않습니다.")
    token = create_access_token(data={"sub": user["id"]})
    return Token(access_token=token, token_type="bearer")


def get_current_user(
    token: str = Depends(oauth2_scheme),
    sb: Client = Depends(get_supabase),
) -> dict:
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="유효하지 않은 토큰입니다.")
    user_id = payload.get("sub")
    res = sb.table("users").select("id, username").eq("id", user_id).execute()
    if not res.data:
        raise HTTPException(status_code=401, detail="사용자를 찾을 수 없습니다.")
    return res.data[0]


@router.get("/me", response_model=UserResponse)
def get_me(current_user: dict = Depends(get_current_user)):
    return UserResponse(id=current_user["id"], username=current_user["username"])
