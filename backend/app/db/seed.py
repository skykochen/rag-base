"""
==========================================
  种子数据初始化 —— 首次启动自动创建管理员
==========================================

【什么是种子数据？】
应用第一次运行时，数据库是空的。种子数据就是「初始必需的数据」：
- 管理员账号（admin）
- 基础角色（admin / user）
没有这些数据，用户无法登录，系统没法用。

【为什么不在数据库迁移里做？】
数据库迁移（alembic）应该只负责表结构变更。
种子数据是业务数据，放在迁移里会混淆两种职责。
而且迁移文件一般只执行一次，种子数据可以重复执行（因为有幂等判断）。

【幂等策略】
- 检查数据库中是否有用户
- 有用户 → 跳过（说明已经初始化过了）
- 无用户 → 创建（首次启动）
- 后续用户改密码、删用户、改角色等手动操作不会被覆盖
"""

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import hash_password
from app.db.models import Role, User, UserStatus
from app.db.repositories.role_repo import RoleRepository
from app.db.repositories.user_repo import UserRepository
from app.db.session import AsyncSessionLocal
from app.services.permission_service import WILDCARD_PERMISSION_TAG

logger = get_logger(__name__)

# 内置角色定义
# 管理员的 permission_tags 含 "*" 通配符，检索时不附加权限过滤
# 普通用户默认只能访问带 "public" 标签的文档
_BUILTIN_ROLES: list[dict] = [
    {
        "name": "admin",
        "description": "系统管理员",
        "permission_tags": [WILDCARD_PERMISSION_TAG],  # 通配符 = 所有权限
    },
    {
        "name": "user",
        "description": "普通用户",
        "permission_tags": ["public"],  # 只能访问公开文档
    },
]


async def seed_default_admin() -> None:
    """
    创建默认管理员和内置角色（仅首次启动时执行一次）。

    【执行流程】
    1. 检查数据库中是否有用户 → 有则跳过
    2. 创建 admin 和 user 两个角色（如已存在则跳过）
    3. 创建 admin 用户，关联到 admin 角色
    4. 提交事务

    这个函数在应用启动时的 lifespan 中调用，
    不影响应用启动速度（数据库空时才会执行）。
    """
    async with AsyncSessionLocal() as session:
        user_repo = UserRepository(session)
        if await user_repo.count_all() > 0:
            return  # 已有用户，跳过

        logger.info("seeding default admin user and built-in roles")
        role_repo = RoleRepository(session)

        # 创建角色（如已存在则跳过）
        roles_by_name: dict[str, Role] = {}
        for spec in _BUILTIN_ROLES:
            existing = await role_repo.get_by_name(spec["name"])
            if existing is not None:
                roles_by_name[spec["name"]] = existing
                continue
            role = Role(
                name=spec["name"],
                description=spec["description"],
                permission_tags=list(spec["permission_tags"]),
            )
            await role_repo.add(role)
            roles_by_name[spec["name"]] = role

        # 创建管理员用户，关联到 admin 角色
        admin_user = User(
            username=settings.default_admin_username,
            password_hash=hash_password(settings.default_admin_password),
            display_name=settings.default_admin_display_name,
            status=UserStatus.ACTIVE,
        )
        admin_user.roles = [roles_by_name["admin"]]
        await user_repo.add(admin_user)
        await session.commit()

        logger.info(
            "seeded admin user: username=%s (please change password ASAP)",
            settings.default_admin_username,
        )
