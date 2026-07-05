import re

from pydantic import BaseModel, field_validator

_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{4,50}$")


class UserCreate(BaseModel):
    username: str
    password: str

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        if not _USERNAME_RE.match(v):
            raise ValueError("아이디는 영문·숫자·언더스코어만 4~50자 사용 가능합니다.")
        return v


class UserResponse(BaseModel):
    id: str
    username: str

    model_config = {"from_attributes": True}


class Token(BaseModel):
    access_token: str
    token_type: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str
