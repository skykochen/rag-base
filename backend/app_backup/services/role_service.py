from app.core.exceptions import ConflictError, NotFoundError
from uuid import UUID

from app.db.models import Role
from app.db.repositories.role_repo import RoleRepository
from sqlalchemy.ext.asyncio import AsyncSession

# 内置角色：不允许删除，避免把 admin 删了登不进系统
PROTECTED_ROLE_NAMES = frozenset({"admin", "user"})

class RoleService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = RoleRepository(session)

    async def list_roles(self) -> list[Role]:
        """列出所有角色。"""
        return await self.repo.list_all()

    async def get_role(self, role_id: UUID) -> Role | None:
        """按 ID 查询角色。"""
        role = await self.repo.get_by_id(role_id)
        if role is None:
            return None
        return role

    async def create_role(self, name: str, description: str, permission_tags: list[str]) -> Role:
        """创建角色。"""
        name = name.strip()
        if not name:
            raise ValueError("角色名不能为空")
        if await self.repo.get_by_name(name) is not None:
            raise ConflictError(f"角色 {name} 已存在")
        role = Role(name=name,
                    description=description.strip(),
                    permission_tags=_normalize_tags(permission_tags),
                    )
        await self.repo.add(role)
        await self.session.commit()
        return role

    async def update_role(self,
                          role_id: UUID,
                          description: str | None,
                          permission_tags: list[str] | None) -> Role:
        """更新角色。"""
        role = await self.repo.get_by_id(role_id)
        if role is None:
            raise NotFoundError("角色不存在")
        # name 故意不允许改：避免权限策略代码里写死的角色名（"admin"）失效
        if description is not None:
            role.description = description.strip()
        if permission_tags is not None:
            role.permission_tags = _normalize_tags(permission_tags)
        await self.session.commit()
        return role

    async def delete_role(self, role_id: UUID) -> None:
        """删除角色。"""
        role = await self.repo.get_by_id(role_id)
        if role is None:
            raise NotFoundError("角色不存在")
        if role.name in PROTECTED_ROLE_NAMES:
            raise ConflictError(f"内置角色 {role.name} 不允许删除")
        await self.repo.delete(role)
        await self.session.commit()

def _normalize_tags(tags: list[str]) -> list[str]:
    """对 permission_tags 做去重、排序、去空。"""
    seen: set[str] = set()
    result: list[str] = []
    for tag in tags:
        t = tag.strip()
        if not t or t in seen:
            continue
        seen.add(t)
        result.append(t)
    return result



