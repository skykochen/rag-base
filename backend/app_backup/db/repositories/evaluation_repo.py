from uuid import UUID
from sqlalchemy import select, func
from app.db.models import EvaluationRun, EvaluationItem
from sqlalchemy.ext.asyncio import AsyncSession
from collections.abc import Sequence


class EvaluationRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, run: EvaluationRun) -> None:
        self.session.add(run)
        await self.session.flush()

    # async def get(self, run_id: UUID) -> EvaluationRun | None:
    #     return await self.session.get(EvaluationRun, run_id)  # type: ignore[return-value]
    async def get(self, run_id: UUID) -> EvaluationRun | None:
        stmt = select(EvaluationRun).where(EvaluationRun.id == run_id)
        return await self.session.scalar(stmt)

    async def list_page(
            self, page: int, page_size: int
    ) -> tuple[list[EvaluationRun], int]:
        page = max(page, 1)
        page_size = max(min(page_size, 100), 1)
        offset = (page - 1) * page_size
        stmt = (
            select(EvaluationRun)
            .order_by(EvaluationRun.created_at.desc(), EvaluationRun.id.desc())
            .offset(offset)
            .limit(page_size)
        )
        items = list((await self.session.execute(stmt)).scalars().all())
        total = int(
            (await self.session.execute(select(func.count(EvaluationRun.id)))).scalar_one()
        )
        return items, total

    async def delete(self, run_id: UUID) -> bool:
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
        if not items:
            return
        self.session.add_all(items)
        await self.session.flush()

    async def add(self, item: EvaluationItem):
        self.session.add(item)
        await self.session.flush()

    async def get(self, item_id: UUID) -> EvaluationItem | None:
        return await self.session.get(EvaluationItem, item_id)

    async def list_by_run(self, run_id: UUID) -> list[EvaluationItem]:
        """取整个 run 的全部 items，用于跑完后批量算 RAGAS。"""
        stmt = (
            select(EvaluationItem)
            .where(EvaluationItem.run_id == run_id)
            .order_by(EvaluationItem.created_at.desc(), EvaluationItem.id.desc())
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
        """取 run 的分页 items，用于展示给用户。"""
        page = max(page, 1)
        page_size = max(min(page_size, 100), 1)
        offset = (page - 1) * page_size

        filters = [EvaluationItem.run_id == run_id]
        if bad_case_only:
            filters.append(EvaluationItem.is_bad_case.is_( True))
        if category:
            filters.append(EvaluationItem.bad_case_category == category)

        stmt = (
            select(EvaluationItem)
            .where(*filters)
            .order_by(EvaluationItem.created_at.desc(), EvaluationItem.id.desc())
            .offset(offset)
            .limit(page_size)
        )
        items = list((await self.session.execute(stmt)).scalars().all())
        #*用于拆包
        total_stmt = select(func.count(EvaluationItem.id)).where(*filters)
        total = int((await self.session.execute(total_stmt)).scalar_one())
        return items, total
