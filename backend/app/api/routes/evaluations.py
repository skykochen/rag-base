"""
==========================================
  评测管理路由 —— 自动化评测系统
==========================================

所有接口要求管理员权限（评测涉及全库数据）。

功能：
- 评测数据集管理（查看可用数据集）
- 评测运行管理（创建、查看、删除）
- 评测结果管理（查看详情、标记 Bad Case）
"""

from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Response

from app.api.deps import DbSession, get_current_admin
from app.api.schemas.evaluations import (
    BadCaseCategoryValue,
    DatasetInfo,
    DatasetListResponse,
    EvaluationItemPage,
    EvaluationItemRead,
    EvaluationItemUpdate,
    EvaluationRunCreate,
    EvaluationRunListItem,
    EvaluationRunPage,
    EvaluationRunRead,
)
from app.services.evaluation_service import EvaluationService, execute_evaluation_run

router = APIRouter(
    prefix="/evaluations",
    tags=["evaluations"],
    dependencies=[Depends(get_current_admin)],
)


@router.get("/datasets", response_model=DatasetListResponse, operation_id="listEvaluationDatasets")
async def list_evaluation_datasets(session: DbSession) -> DatasetListResponse:
    """列出可用的评测集（evaluation/datasets/ 目录下的 jsonl 文件）。"""
    service = EvaluationService(session)
    items = service.list_datasets()
    return DatasetListResponse(
        items=[DatasetInfo(name=name, size=size) for name, size in items]
    )


@router.post("/runs", response_model=EvaluationRunRead, status_code=201, operation_id="createEvaluationRun")
async def create_evaluation_run(
    payload: EvaluationRunCreate,
    session: DbSession,
    background_tasks: BackgroundTasks,
) -> EvaluationRunRead:
    """
    创建评测运行。

    BackgroundTasks 是 FastAPI 的内置功能，可以在响应返回后异步执行任务。
    这里创建 run 后立即返回，实际的评测在后台运行。
    """
    service = EvaluationService(session)
    run = await service.create_run(name=payload.name, dataset_name=payload.dataset_name)
    background_tasks.add_task(execute_evaluation_run, run.id)
    return EvaluationRunRead.model_validate(run)


@router.get("/runs", response_model=EvaluationRunPage, operation_id="listEvaluationRuns")
async def list_evaluation_runs(
    session: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> EvaluationRunPage:
    """分页列出评测运行记录。"""
    service = EvaluationService(session)
    items, total = await service.list_runs(page=page, page_size=page_size)
    return EvaluationRunPage(
        items=[EvaluationRunListItem.model_validate(r) for r in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/runs/{run_id}", response_model=EvaluationRunRead, operation_id="getEvaluationRun")
async def get_evaluation_run(run_id: UUID, session: DbSession) -> EvaluationRunRead:
    """获取单次评测运行的详细信息。"""
    service = EvaluationService(session)
    run = await service.get_run(run_id)
    return EvaluationRunRead.model_validate(run)


@router.delete("/runs/{run_id}", status_code=204, operation_id="deleteEvaluationRun")
async def delete_evaluation_run(run_id: UUID, session: DbSession) -> Response:
    """删除评测运行及其全部结果数据。"""
    service = EvaluationService(session)
    await service.delete_run(run_id)
    return Response(status_code=204)


@router.get("/runs/{run_id}/items", response_model=EvaluationItemPage, operation_id="listEvaluationItems")
async def list_evaluation_items(
    run_id: UUID,
    session: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    bad_case_only: bool = Query(False),
    category: BadCaseCategoryValue | None = Query(None),
) -> EvaluationItemPage:
    """
    分页查看评测结果。
    支持筛选：仅看 Bad Case、按归因分类查看。
    """
    service = EvaluationService(session)
    items, total = await service.list_items(
        run_id,
        page=page,
        page_size=page_size,
        bad_case_only=bad_case_only,
        category=category,
    )
    return EvaluationItemPage(
        items=[EvaluationItemRead.model_validate(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/items/{item_id}", response_model=EvaluationItemRead, operation_id="getEvaluationItem")
async def get_evaluation_item(item_id: UUID, session: DbSession) -> EvaluationItemRead:
    """获取单条评测结果的详细信息。"""
    service = EvaluationService(session)
    item = await service.get_item(item_id)
    return EvaluationItemRead.model_validate(item)


@router.patch("/items/{item_id}", response_model=EvaluationItemRead, operation_id="updateEvaluationItem")
async def update_evaluation_item(
    item_id: UUID,
    payload: EvaluationItemUpdate,
    session: DbSession,
) -> EvaluationItemRead:
    """
    人工覆盖 Bad Case 归因分析。

    系统自动识别 Bad Case 并给出归因类别，
    但有时需要人工修正（比如系统误判或需要补充备注）。
    """
    service = EvaluationService(session)
    item = await service.update_item_bad_case(
        item_id,
        bad_case_category=payload.bad_case_category,
        bad_case_note=payload.bad_case_note,
        is_bad_case=payload.is_bad_case,
    )
    return EvaluationItemRead.model_validate(item)
