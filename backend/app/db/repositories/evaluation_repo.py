"""
==========================================
  评测数据访问（EvaluationRun / EvaluationItem）
==========================================

评测模块的数据访问。负责管理评测运行记录和每条评测 case 的结果。
"""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EvaluationItem, EvaluationRun


class EvaluationRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, run: EvaluationRun) -> None:
        """创建评测运行记录。"""
        self.session.add(run)
        await self.session.flush()

    async def get(self, run_id: UUID) -> EvaluationRun | None:
        """查询评测运行。"""
        return await self.session.get(EvaluationRun, run_id)

    async def list_page(self, page: int, page_size: int) -> tuple[list[EvaluationRun], int]:
        """分页查询评测运行列表。"""
        page = max(page, 1)
        page_size = max(min(page_size, 100), 1)
        offset = (page - 1) * page_size

        stmt = (
            select(EvaluationRun)
            .order_by(EvaluationRun.created_at.desc(), EvaluationRun.id.desc())
            .limit(page_size)
            .offset(offset)
        )
        items = list((await self.session.execute(stmt)).scalars().all())
        total = int(
            (await self.session.execute(select(func.count(EvaluationRun.id)))).scalar_one()
        )
        return items, total

    async def delete(self, run_id: UUID) -> bool:
        """删除评测运行及其关联的 items。"""
        run = await self.get(run_id)
        if run is None:
            return False
        await self.session.delete(run)
        await self.session.flush()
        return True


class EvaluationItemRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def bulk_add(self, items: Sequence[EvaluationItem]) -> None:
        """批量添加评测结果。"""
        if not items:
            return
        self.session.add_all(items)
        await self.session.flush()

    async def add(self, item: EvaluationItem) -> None:
        """添加单条评测结果。"""
        self.session.add(item)
        await self.session.flush()

    async def get(self, item_id: UUID) -> EvaluationItem | None:
        """查询单条评测结果。"""
        return await self.session.get(EvaluationItem, item_id)

    async def list_by_run(self, run_id: UUID) -> list[EvaluationItem]:
        """获取某次评测的全部结果。"""
        stmt = (
            select(EvaluationItem)
            .where(EvaluationItem.run_id == run_id)
            .order_by(EvaluationItem.created_at.asc(), EvaluationItem.id.asc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_page(
        self,
        run_id: UUID,
        page: int,
        page_size: int,
        *,
        bad_case_only: bool = False,
        category: str | None = None,
    ) -> tuple[list[EvaluationItem], int]:
        """分页查询评测结果，支持筛选。"""
        page = max(page, 1)
        page_size = max(min(page_size, 100), 1)
        offset = (page - 1) * page_size

        filters = [EvaluationItem.run_id == run_id]
        if bad_case_only:
            filters.append(EvaluationItem.is_bad_case.is_(True))
        if category:
            filters.append(EvaluationItem.bad_case_category == category)

        stmt = (
            select(EvaluationItem)
            .where(*filters)
            .order_by(EvaluationItem.created_at.asc(), EvaluationItem.id.asc())
            .limit(page_size)
            .offset(offset)
        )
        items = list((await self.session.execute(stmt)).scalars().all())

        total_stmt = select(func.count(EvaluationItem.id)).where(*filters)
        total = int((await self.session.execute(total_stmt)).scalar_one())
        return items, total
