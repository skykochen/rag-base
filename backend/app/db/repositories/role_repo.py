"""
==========================================
  RoleRepository —— roles 表的数据访问
==========================================

角色表的数据访问。角色数量通常很少（几个到十几个），所以不分页。
"""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Role


class RoleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, role_id: UUID) -> Role | None:
        """按主键查询角色。"""
        return await self.session.get(Role, role_id)

    async def get_by_name(self, name: str) -> Role | None:
        """按角色名查询（角色名是唯一约束）。"""
        stmt = select(Role).where(Role.name == name)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_all(self) -> list[Role]:
        """
        查询所有角色。

        【为什么不分页？】
        角色数量天然很少（通常只有 admin、user 等几个），
        一次性全量返回即可。
        """
        stmt = select(Role).order_by(Role.created_at.asc(), Role.id.asc())
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_many(self, role_ids: Sequence[UUID]) -> list[Role]:
        """
        批量查询角色（根据 ID 列表）。

        使用场景：给用户分配角色时，把 role_id 列表转成 Role 对象列表。
        """
        if not role_ids:
            return []
        stmt = select(Role).where(Role.id.in_(list(role_ids)))
        return list((await self.session.execute(stmt)).scalars().all())

    async def add(self, role: Role) -> Role:
        """新增角色。"""
        self.session.add(role)
        await self.session.flush()
        return role

    async def delete(self, role: Role) -> None:
        """删除角色。"""
        await self.session.delete(role)
        await self.session.flush()
