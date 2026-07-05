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
from app.schemas.user import ChangePasswordRequest, Token, UserCreate, UserResponse

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
    token = create_access_token(data={"sub": user["id"], "username": user["username"]})
    return Token(access_token=token, token_type="bearer")


def get_current_user(
    token: str = Depends(oauth2_scheme),
) -> dict:
    # DB 조회 없이 JWT claim만으로 인증 — username은 토큰 발급 시(login) 이미
    # 검증된 값을 그대로 embed 했으므로 재조회가 불필요하다 (매 요청마다 users
    # SELECT 하나씩 없어짐). 트레이드오프: 이 앱에는 계정 삭제/비활성화 기능이
    # 없으므로(레포 전체에서 users DELETE 사용처 없음 확인) "탈퇴한 사용자가
    # 만료 전 토큰으로 계속 접근 가능"한 위험이 현재는 없다 — 추후 계정
    # 삭제/정지 기능이 추가되면 이 지점에서 다시 DB 검증을 넣어야 한다.
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="유효하지 않은 토큰입니다.")
    user_id = payload.get("sub")
    username = payload.get("username")
    if not user_id or not username:
        raise HTTPException(status_code=401, detail="유효하지 않은 토큰입니다.")
    return {"id": user_id, "username": username}


@router.get("/me", response_model=UserResponse)
def get_me(current_user: dict = Depends(get_current_user)):
    return UserResponse(id=current_user["id"], username=current_user["username"])


@router.post("/change-password")
def change_password(
    body: ChangePasswordRequest,
    current_user: dict = Depends(get_current_user),
    sb: Client = Depends(get_supabase),
):
    res = sb.table("users").select("id, password_hash").eq("id", current_user["id"]).execute()
    if not res.data:
        raise HTTPException(status_code=401, detail="사용자를 찾을 수 없습니다.")
    user = res.data[0]
    if not verify_password(body.current_password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="현재 비밀번호가 올바르지 않습니다.")
    if not validate_password(body.new_password):
        raise HTTPException(status_code=422, detail="새 비밀번호는 영문과 숫자를 포함하여 6~72자여야 합니다.")
    if body.current_password == body.new_password:
        raise HTTPException(status_code=422, detail="새 비밀번호는 현재 비밀번호와 달라야 합니다.")
    sb.table("users").update({"password_hash": get_password_hash(body.new_password)}).eq("id", user["id"]).execute()
    return {"message": "비밀번호가 변경되었습니다."}
