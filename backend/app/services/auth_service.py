"""
==========================================
  AuthService —— 登录校验 + JWT 签发
==========================================

【职责范围】
  · authenticate：校验用户名 + 密码 + 账户状态，统一返回 None 避免侧信道
  · issue_token：基于 user.id 签发 JWT access token

【不做什么】
  · 不检查 token 有效期 / 刷新 token / 登出——这些在 security 模块和路由层
  · 不管理 session——auth_service 只读，调用方 commit 不commit 没影响
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.security import create_access_token, verify_password
from app.db.models import User, UserStatus
from app.db.repositories.user_repo import UserRepository

logger = get_logger(__name__)


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.user_repo = UserRepository(session)

    async def authenticate(self, username: str, password: str) -> User | None:
        user = await self.user_repo.get_by_username(username)
        if user is None:
            return None
        if user.status != UserStatus.ACTIVE:
            logger.info("login refused (disabled): username=%s", username)
            return None
        if not verify_password(password, user.password_hash):
            return None
        return user

    @staticmethod
    def issue_token(user: User) -> str:
        return create_access_token(str(user.id))
