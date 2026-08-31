"""
==========================================
  文档管理路由 —— 上传、查看、删除文档
==========================================

文档是知识库的核心实体。这个模块负责文档的整个生命周期管理。

接口权限划分：
- 读接口（list / get / chunks / download）：登录用户可访问，按权限过滤
- 写接口（upload / delete / retry / reindex）：仅管理员可操作

【前端轮询机制】
文档上传后由 Celery 异步处理，前端通过定时轮询 list 接口
获取文档状态和任务进度。
"""

import json
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, File, Form, Header, Query, Response, UploadFile

from app.api.deps import CurrentAdmin, CurrentUser, DbSession, RateLimited
from app.api.schemas.documents import (
    DocumentChunkDetail,
    DocumentChunkListResponse,
    DocumentChunkRead,
    DocumentChunkStats,
    DocumentListResponse,
    DocumentPermissionTagsUpdate,
    DocumentRead,
    DocumentStatusValue,
    IngestionTaskRead,
)
from app.db.models import Document, DocumentStatus
from app.services.document_service import DocumentService
from app.services.permission_service import (
    compute_user_permission_tags,
    is_admin,
)

router = APIRouter(prefix="/documents", tags=["documents"])

_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _viewer_tags(user) -> list[str] | None:
    """
    根据用户角色返回权限标签。

    - 管理员 → None（service 内部会转为"不限"）
    - 普通用户 → 合并用户所有角色的权限标签
    """
    return None if is_admin(user) else compute_user_permission_tags(user)


async def _to_document_read(document: Document, service: DocumentService) -> DocumentRead:
    """
    把 Document ORM 对象转成接口响应格式。

    额外附带最近一次入库任务的信息（latest_task），
    前端轮询时可以直接看到进度。
    """
    latest = await service.get_latest_task(document.id)
    return DocumentRead.model_validate(
        {
            **{c.name: getattr(document, c.name) for c in document.__table__.columns},
            "latest_task": IngestionTaskRead.model_validate(latest)
            if latest is not None
            else None,
        }
    )


@router.post("", response_model=DocumentRead, status_code=201, operation_id="uploadDocument")
async def upload_document(
    admin: CurrentAdmin,
    _rate_limit: RateLimited,
    session: DbSession,
    file: UploadFile = File(..., description="待上传文档"),
    permission_tags: str | None = Form(
        default=None,
        description='JSON 数组字符串，例如 ["public","hr"]',
    ),
) -> DocumentRead:
    """
    上传文档。

    流程：
    1. 接收文件 → 计算 SHA256 → 校验是否重复
    2. 上传到 COS 对象存储
    3. 创建文档数据库记录（状态：uploading）
    4. 提交 Celery 异步任务进行解析和向量化
    5. 立即返回，前端轮询状态

    参数：
    - file: 上传的文件（PDF / DOCX / Markdown / HTML）
    - permission_tags: 权限标签，如 ["public","hr"]，不传则公开
    """
    tags: list[str] = []
    if permission_tags:
        try:
            parsed = json.loads(permission_tags)
        except json.JSONDecodeError:
            parsed = [permission_tags]
        if isinstance(parsed, list):
            tags = [str(t) for t in parsed]

    service = DocumentService(session)
    document = await service.upload(
        file,
        created_by=admin.id,
        permission_tags=tags,
    )
    return await _to_document_read(document, service)


@router.get("", response_model=DocumentListResponse, operation_id="listDocuments")
async def list_documents(
    user: CurrentUser,
    session: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: DocumentStatusValue | None = Query(None, description="按文档状态筛选"),
) -> DocumentListResponse:
    """分页查询文档列表，可筛选状态，按创建时间倒序。"""
    service = DocumentService(session)
    items, total = await service.list_documents(
        page, page_size,
        status=DocumentStatus(status) if status else None,
        permission_tags=_viewer_tags(user),
    )
    return DocumentListResponse(
        items=[await _to_document_read(d, service) for d in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{document_id}", response_model=DocumentRead, operation_id="getDocument")
async def get_document(
    document_id: UUID,
    user: CurrentUser,
    session: DbSession,
) -> DocumentRead:
    """获取单个文档的详细信息。"""
    service = DocumentService(session)
    document = await service.get(document_id, permission_tags=_viewer_tags(user))
    return await _to_document_read(document, service)


@router.delete("/{document_id}", status_code=204, operation_id="deleteDocument")
async def delete_document(
    _: CurrentAdmin,
    document_id: UUID,
    session: DbSession,
) -> Response:
    """删除文档（从数据库和 COS 中删除）。"""
    service = DocumentService(session)
    await service.delete(document_id)
    return Response(status_code=204)


@router.post("/{document_id}/retry", response_model=DocumentRead, operation_id="retryDocument")
async def retry_document(
    _: CurrentAdmin,
    document_id: UUID,
    session: DbSession,
) -> DocumentRead:
    """重新处理失败的文档（重新执行入库流程）。"""
    service = DocumentService(session)
    document = await service.retry(document_id)
    return await _to_document_read(document, service)


@router.post("/{document_id}/reindex", response_model=DocumentRead, operation_id="reindexDocument")
async def reindex_document(
    _: CurrentAdmin,
    _rate_limit: RateLimited,
    document_id: UUID,
    session: DbSession,
    file: UploadFile = File(..., description="新版本文件（MIME 必须与原文档一致）"),
) -> DocumentRead:
    """
    增量重建索引：上传新版本文件，仅对变化内容重新处理。

    效率优于全量重新入库（retry），因为只处理内容变更的 chunk。
    """
    service = DocumentService(session)
    document = await service.reindex(document_id, file)
    return await _to_document_read(document, service)


@router.patch(
    "/{document_id}/permission-tags",
    response_model=DocumentRead,
    operation_id="updateDocumentPermissionTags",
)
async def update_permission_tags(
    _: CurrentAdmin,
    document_id: UUID,
    session: DbSession,
    payload: DocumentPermissionTagsUpdate,
) -> DocumentRead:
    """更新文档的权限标签。"""
    service = DocumentService(session)
    document = await service.update_permission_tags(document_id, payload.permission_tags)
    return await _to_document_read(document, service)


@router.get("/{document_id}/file", operation_id="downloadDocument")
async def download_document(
    document_id: UUID,
    session: DbSession,
    download: int = Query(0, ge=0, le=1, description="1=强制下载, 0=尝试内联预览"),
    token: str | None = Query(None, description="Bearer token（iframe/新窗口无法带 header 时使用）"),
    authorization: str | None = Header(None, alias="Authorization"),
) -> Response:
    """
    下载/预览文档源文件。

    支持两种认证方式（优先使用 header）：
    1. Authorization header（常规 fetch 请求）
    2. ?token= 查询参数（浏览器直接打开或 iframe 内嵌时使用）
    """
    from app.api.deps import get_current_user

    effective_auth = authorization or (f"Bearer {token}" if token else None)
    user = await get_current_user(session, effective_auth)

    service = DocumentService(session)
    document = await service.get(document_id, permission_tags=_viewer_tags(user))
    content = await service.file_service.download(document.cos_object_key)

    force_attachment = download == 1 or document.mime_type == _DOCX_MIME
    disposition = "attachment" if force_attachment else "inline"
    filename_quoted = quote(document.name, safe="")

    return Response(
        content=content,
        media_type=document.mime_type,
        headers={
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{filename_quoted}",
        },
    )


@router.get("/{document_id}/chunks", response_model=DocumentChunkListResponse, operation_id="listDocumentChunks")
async def list_document_chunks(
    document_id: UUID,
    user: CurrentUser,
    session: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> DocumentChunkListResponse:
    """
    查看文档的切片列表（入库后才有数据）。

    附带切片统计信息（总数、平均长度等），方便了解文档切分情况。
    """
    service = DocumentService(session)
    items, total, stats = await service.list_chunks(
        document_id, page, page_size, permission_tags=_viewer_tags(user)
    )
    return DocumentChunkListResponse(
        items=[DocumentChunkRead.from_orm_chunk(c) for c in items],
        total=total,
        page=page,
        page_size=page_size,
        stats=DocumentChunkStats(
            total=stats.total,
            avg_length=stats.avg_length,
            min_length=stats.min_length,
            max_length=stats.max_length,
        ) if stats is not None else None,
    )


@router.get("/{document_id}/chunks/{chunk_id}", response_model=DocumentChunkDetail, operation_id="getDocumentChunk")
async def get_document_chunk(
    document_id: UUID,
    chunk_id: UUID,
    user: CurrentUser,
    session: DbSession,
) -> DocumentChunkDetail:
    """获取单个文档切片的详细信息。"""
    service = DocumentService(session)
    chunk = await service.get_chunk(
        document_id, chunk_id, permission_tags=_viewer_tags(user)
    )
    return DocumentChunkDetail.from_orm_chunk(chunk)
