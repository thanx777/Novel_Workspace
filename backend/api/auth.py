"""
JWT Authentication Module for FastAPI.

Provides:
- JWT token creation / verification
- Password hashing (bcrypt)
- FastAPI dependencies: require_auth, require_admin
- AUTH_DISABLED mode for local development
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
from datetime import datetime, timedelta
from typing import Optional
import os

security = HTTPBearer(auto_error=False)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ALGORITHM = "HS256"


def get_auth_secret() -> str:
    """获取 JWT 签名密钥"""
    secret = os.environ.get("AUTH_SECRET", "").strip()
    if not secret:
        secret = os.environ.get("NOVEL_WORKSPACE_SECRET", "").strip()
    if not secret:
        secret = "dev-only-secret-change-in-production"
    return secret


def get_token_expire_hours() -> int:
    return int(os.environ.get("AUTH_TOKEN_EXPIRE_HOURS", "24"))


def is_auth_disabled() -> bool:
    return os.environ.get("AUTH_DISABLED", "").lower() in ("true", "1", "yes")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(hours=get_token_expire_hours()))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, get_auth_secret(), algorithm=ALGORITHM)


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """FastAPI 依赖：获取当前用户，认证失败抛 401"""
    if is_auth_disabled():
        return {"username": "dev", "role": "admin"}
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload = jwt.decode(credentials.credentials, get_auth_secret(), algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        return {"username": username, "role": payload.get("role", "user")}
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


async def require_auth(user=Depends(get_current_user)):
    """FastAPI 依赖：要求认证"""
    return user


async def require_admin(user=Depends(get_current_user)):
    """FastAPI 依赖：要求管理员权限"""
    if is_auth_disabled():
        return user
    if user.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user
