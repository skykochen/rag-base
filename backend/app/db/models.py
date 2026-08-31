"""
==========================================
  ORM 模型 —— 数据库表结构的 Python 映射
==========================================

【什么是 ORM 模型？】
每个类对应一张数据库表，每个类属性对应一个表字段。
例如 User 类对应 users 表，User.username 对应 username 列。

【为什么所有模型放在一个文件？】
- alembic autogenerate 需要扫描所有模型才能自动生成迁移脚本
- 如果分散到多个文件，必须在某个入口统一 import
- 集中到一个文件是最简单的做法，项目初期模型不多

【每个模型的生命周期标记】
注释中标记了"第 X 章"表示这个模型是在哪期教程中引入的，
方便你按章节递进学习。

更多说明见：
- app/db/base.py    — ORM 基类（DeclarativeBase）
- app/db/session.py — 数据库连接管理
"""

from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import settings
from app.db.base import Base


# ════════════════════════════════════════════════════════════════
# 第 3 章：文档模型
# 文档入库的核心数据结构
# ════════════════════════════════════════════════════════════════


class DocumentStatus(str, Enum):
    """
    文档生命周期状态。

    文档从上传到可被检索，需要经过一系列处理步骤。
    这个枚举定义了每一步的状态值。

    状态流转：
    uploading → parsing → indexing → ready（正常完成）
    uploading → parsing → indexing → failed（某步出错）

    【为什么用 str 继承？】
    继承 str 使得枚举值可以直接与字符串比较：
    doc.status == "ready"  ✅ 而不需要 doc.status == DocumentStatus.READY
    Pydantic 也自动接受字符串输入
    """
    UPLOADING = "uploading"  # 已上传到 COS，但还没开始处理
    PARSING = "parsing"      # Docling 正在解析文档内容
    INDEXING = "indexing"    # 正在切分文本并向量化
    READY = "ready"          # 处理完成，可被检索
    FAILED = "failed"        # 处理失败，查看 error_message 了解原因


class Document(Base):
    """
    文档主表。

    用户上传的文件，经过入库处理后，元数据存在这里。
    实际的文件内容（PDF/DOCX 等源文件）存储在腾讯云 COS 中。
    """

    __tablename__ = "documents"  # 数据库表名

    # UUID 主键，自动生成
    # 使用 UUID 而非自增 ID 的好处：
    # 1. 不暴露数据量（用户数/文档数）
    # 2. 无法被枚举遍历（安全考量）
    # 3. 分布式环境下不会冲突
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    # 文档名称（用户上传时的文件名）
    name: Mapped[str] = mapped_column(String(512), nullable=False)

    # 文件 SHA256 哈希值（十六进制，64 位）
    # 唯一约束 + 索引，用于重复上传检测（幂等校验）
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)

    # MIME 类型，如 application/pdf、text/markdown
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)

    # 文件大小（字节），用 BigInteger（最大可存 9EB）
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # ──────────── 存储信息 ────────────
    # 文件存储在腾讯云 COS 中
    storage_provider: Mapped[str] = mapped_column(String(32), nullable=False, default="cos")
    cos_bucket: Mapped[str] = mapped_column(String(128), nullable=False)      # 存储桶
    cos_object_key: Mapped[str] = mapped_column(String(512), nullable=False)   # 对象路径
    cos_region: Mapped[str] = mapped_column(String(64), nullable=False)        # 地域

    # ──────────── 处理状态 ────────────
    status: Mapped[DocumentStatus] = mapped_column(
        String(32), nullable=False, default=DocumentStatus.UPLOADING
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)  # 失败原因

    # 文档版本号：每次增量重建（reindex）成功后 +1
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # ──────────── 权限标签（第 11 章引入）────────────
    # 空数组 = "公开"，任意登录用户可访问
    # 非空数组 = 用户必须持有至少一个匹配的标签才能访问
    # 管理员持 "*" 通配符，无视权限过滤
    permission_tags: Mapped[list[str]] = mapped_column(
        ARRAY(String()), nullable=False, default=list, server_default="{}"
    )

    # 上传者（用户被删除后置 NULL，文档历史保留）
    created_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # ──────────── 时间戳 ────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # ──────────── 关联关系 ────────────
    # 一个文档有多个切片，删除文档时级联删除全部切片
    chunks: Mapped[list["DocumentChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", passive_deletes=True
    )
    # 一个文档有多次入库任务记录
    ingestion_tasks: Mapped[list["IngestionTask"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="IngestionTask.created_at.desc()",
    )


class DocumentChunk(Base):
    """
    文档切片表。

    RAG 系统的核心数据表！
    文档被切分成多个文本片段（chunks），每个片段都做了向量化。
    用户提问时，系统在你的问题向量和这些切片向量之间做相似度搜索。

    表名：document_chunks（复数）
    """

    __tablename__ = "document_chunks"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    # 所属文档的外键，级联删除
    document_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # 切片原文内容
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # 切片原文的向量表示（核心！）
    # 维度由 settings.embedding_dim 控制（默认 1024）
    # 【重要】如果改了维度，需要建新的数据库迁移
    embedding: Mapped[list[float]] = mapped_column(Vector(settings.embedding_dim), nullable=False)

    # ──────────── 元信息 ────────────
    page_no: Mapped[int | None] = mapped_column(Integer, nullable=True)         # 在 PDF 中的页码
    section_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)  # 章节路径
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)            # 在文档中的序号
    chunk_hash: Mapped[str] = mapped_column(String(32), nullable=False, index=True)  # md5(content)
    extra_metadata: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)

    # ──────────── 全文检索索引列（第 6 章引入）────────────
    # PostgreSQL 的 GENERATED ALWAYS 列：
    # 它由 content 字段自动计算生成，应用层不需要写入
    # to_tsvector('chinese_zh', content) 做了中文分词并建立全文索引
    content_tsv: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('chinese_zh', content)", persisted=True),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # 关联的文档对象
    document: Mapped[Document] = relationship(back_populates="chunks")


# ════════════════════════════════════════════════════════════════
# 第 4 章：会话与消息模型
# 多轮对话相关
# ════════════════════════════════════════════════════════════════


class MessageRole(str, Enum):
    """消息角色：谁发的这条消息。"""
    USER = "user"           # 用户发的
    ASSISTANT = "assistant"  # AI 回复的
    SYSTEM = "system"        # 系统提示


class Conversation(Base):
    """
    会话模型。

    一次对话的容器。用户创建会话后，在会话内进行多轮问答。
    一个会话包含多条消息（一问一答）。
    """

    __tablename__ = "conversations"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    title: Mapped[str] = mapped_column(String(256), nullable=False, default="新对话")
    user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # 一个会话有多条消息，删除会话时自动删除全部消息
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Message.created_at",
    )


class Message(Base):
    """
    消息模型。

    会话中的一条消息，可以是用户提问或 AI 回复。
    AI 回复的消息会附带引用（citations），指向用到的文档切片。
    """

    __tablename__ = "messages"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[MessageRole] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # 扩展信息（JSONB 灵活存储）：
    # - refused: 是否拒答
    # - query_route: 查询路由信息
    # - agent_steps: Agent 决策步骤
    # - trace_id: LangSmith 追踪 ID
    # - cache_hit: 是否命中语义缓存
    extra_metadata: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    conversation: Mapped[Conversation] = relationship(back_populates="messages")

    # AI 回复消息的引用列表
    citations: Mapped[list["AnswerCitation"]] = relationship(
        back_populates="message",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="AnswerCitation.ordinal",
    )


class AnswerCitation(Base):
    """
    答案引用快照表。

    AI 回答中引用了哪些文档切片。
    【快照设计】：即使原切片之后被更新或删除，历史对话中的引用仍然保留。
    """

    __tablename__ = "answer_citations"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    message_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)  # 引用编号（从 1 开始）

    # 原文档/切片可能被删除，ON DELETE SET NULL 保留快照
    document_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
    )
    chunk_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("document_chunks.id", ondelete="SET NULL"),
        nullable=True,
    )
    document_name: Mapped[str] = mapped_column(String(512), nullable=False)
    page_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quote: Mapped[str] = mapped_column(Text, nullable=False)  # 引用的原文

    # 检索元数据（JSONB）：向量排名、关键词排名、分数等
    retrieval_meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    message: Mapped[Message] = relationship(back_populates="citations")


# ════════════════════════════════════════════════════════════════
# 第 10 章：评测模型
# 自动化评测相关
# ════════════════════════════════════════════════════════════════


class EvaluationRunStatus(str, Enum):
    """评测运行状态。"""
    RUNNING = "running"      # 进行中
    COMPLETED = "completed"  # 已完成
    FAILED = "failed"        # 运行异常中止


class EvaluationRun(Base):
    """
    单次评测运行记录。

    一次评测 = 对一个评测数据集运行一遍 RAG 流程，
    得到每条的指标分数和整体聚合指标。
    """

    __tablename__ = "evaluation_runs"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    dataset_name: Mapped[str] = mapped_column(String(128), nullable=False)
    dataset_size: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[EvaluationRunStatus] = mapped_column(String(16), nullable=False)

    progress_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress_completed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # 聚合指标（跑完后回填）
    faithfulness: Mapped[float | None] = mapped_column(Float, nullable=True)         # 忠实度
    answer_relevancy: Mapped[float | None] = mapped_column(Float, nullable=True)     # 答案相关性
    context_precision: Mapped[float | None] = mapped_column(Float, nullable=True)    # 上下文精确率
    context_recall: Mapped[float | None] = mapped_column(Float, nullable=True)       # 上下文召回率
    citation_hit_rate: Mapped[float | None] = mapped_column(Float, nullable=True)    # 引用命中率
    refusal_accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)     # 拒答准确率
    avg_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)       # 平均延迟
    avg_first_token_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    items: Mapped[list["EvaluationItem"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class EvaluationItem(Base):
    """
    单条评测结果。

    记录一条评测数据的输入、输出和各项指标。
    「输入」从评测集 JSONL 复制过来，不关联原文件。
    这样评测集后续更新不会影响历史评测结果的对比。
    """

    __tablename__ = "evaluation_items"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("evaluation_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ──── 输入快照（从 JSONL 复制）────
    case_id: Mapped[str] = mapped_column(String(64), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    expected_answer: Mapped[str] = mapped_column(Text, nullable=False)
    expected_document_names: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    expected_keywords: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    should_refuse: Mapped[bool] = mapped_column(Boolean, nullable=False)
    tags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    # ──── 实际输出快照 ────
    actual_answer: Mapped[str] = mapped_column(Text, nullable=False, default="")
    actual_refused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    citations: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    retrieved_chunks_meta: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    query_route: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    agent_steps: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    verify_result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    first_token_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ──── 指标分数 ────
    faithfulness: Mapped[float | None] = mapped_column(Float, nullable=True)
    answer_relevancy: Mapped[float | None] = mapped_column(Float, nullable=True)
    context_precision: Mapped[float | None] = mapped_column(Float, nullable=True)
    context_recall: Mapped[float | None] = mapped_column(Float, nullable=True)
    citation_hit: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    refusal_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)

    # ──── Bad Case 归因 ────
    is_bad_case: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    bad_case_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bad_case_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    run: Mapped[EvaluationRun] = relationship(back_populates="items")


# ════════════════════════════════════════════════════════════════
# 第 11 章：认证与权限模型
# ════════════════════════════════════════════════════════════════


class UserStatus(str, Enum):
    """用户状态。"""
    ACTIVE = "active"        # 正常
    DISABLED = "disabled"    # 被禁用（无法登录）


# 用户-角色 多对多关联表。
# 一个用户可以有多个角色，一个角色可以分配给多个用户。
# 这里用 Table 而不是 ORM 模型，因为关联表不需要业务字段。
user_roles_table = Table(
    "user_roles",
    Base.metadata,
    Column(
        "user_id",
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "role_id",
        PGUUID(as_uuid=True),
        ForeignKey("roles.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class User(Base):
    """
    用户主表。

    记录用户的基本信息。密码使用 bcrypt 加密存储（不存明文）。
    用户的权限通过角色（roles）间接获得。
    """

    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)  # bcrypt 哈希
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[UserStatus] = mapped_column(
        String(16), nullable=False, default=UserStatus.ACTIVE
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # 用户关联的角色（多对多）
    # lazy="selectin"：查询用户时自动用额外 SELECT 加载角色
    roles: Mapped[list["Role"]] = relationship(
        secondary=user_roles_table,
        back_populates="users",
        lazy="selectin",
    )


class Role(Base):
    """
    RBAC 角色模型。

    RBAC = Role-Based Access Control（基于角色的访问控制）。

    用户不直接拥有权限，而是通过角色获得权限。
    例如：用户 A 有 admin 角色 → 管理员权限
         用户 B 有 user 角色 → 普通用户权限

    permission_tags：角色持有的权限标签数组
    - 用户的最终权限 = 所有角色 tags 的并集
    - 特殊值 "*" 表示通配（管理员）
    """

    __tablename__ = "roles"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    permission_tags: Mapped[list[str]] = mapped_column(
        ARRAY(String()), nullable=False, default=list, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    users: Mapped[list[User]] = relationship(
        secondary=user_roles_table,
        back_populates="roles",
    )


# ════════════════════════════════════════════════════════════════
# 第 12 章：入库任务模型
# Celery 异步任务追踪
# ════════════════════════════════════════════════════════════════


class IngestionTaskType(str, Enum):
    """入库任务类型。"""
    INGEST = "ingest"      # 首次入库（解析 → 切分 → 全量 embedding → 写入）
    REINDEX = "reindex"    # 增量重建（仅对变化的 chunk 重新 embedding）


class IngestionTaskStatus(str, Enum):
    """任务生命周期状态。"""
    PENDING = "pending"   # 已创建，等待 worker 拉取
    RUNNING = "running"   # worker 正在执行
    SUCCESS = "success"   # 执行成功
    FAILED = "failed"     # 执行失败


class IngestionTask(Base):
    """
    文档入库任务记录。

    Celery Worker 执行文档入库时，会更新这个表的记录。
    前端轮询文档列表时，可以看到任务的进度和状态。

    表名：ingestion_tasks
    """

    __tablename__ = "ingestion_tasks"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_type: Mapped[IngestionTaskType] = mapped_column(String(16), nullable=False)
    status: Mapped[IngestionTaskStatus] = mapped_column(
        String(16), nullable=False, default=IngestionTaskStatus.PENDING
    )
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 进度信息
    progress_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress_done: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    document: Mapped[Document] = relationship(back_populates="ingestion_tasks")
