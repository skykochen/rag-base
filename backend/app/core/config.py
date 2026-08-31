"""
==========================================
  应用配置中心 —— 所有配置项集中管理
==========================================

这个文件是项目的「配置总入口」，负责从 .env 文件读取环境变量。

【为什么需要这个文件？】
- 如果每个模块各自读环境变量，散落在各处，改配置时得满项目找
- 这里统一管理，其他模块只需 from app.core.config import settings 就能拿到配置
- 自动类型转换：环境变量都是字符串（"true"/"1024"），这里转成 bool/int

【学习提示】
- 建议第一个看这个文件，了解项目有哪些可配置项
- 后续看到某个功能时（如缓存、限流），再回来看对应的配置项
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


# 项目根目录路径：指向 rag-knowledge-base/（与 docker-compose.yml 同级）
# Path(__file__)              → 当前文件路径: .../backend/app/core/config.py
# .resolve()                  → 解析符号链接，拿到绝对路径
# .parents[3]                 → 上三级: core/ → app/ → backend/ → 项目根目录
# 这样无论从哪里启动程序，都能正确找到项目根目录下的 .env 文件
PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """
    配置类，继承 pydantic-settings 的 BaseSettings。

    【为什么用 pydantic-settings？】
    - 自动从 .env 读取：配置好 env_file 路径后，字段名会自动匹配 .env 中的变量名
    - 类型校验：字段类型注解会自动转换和校验环境变量的值
    - 提供默认值：大部分字段有默认值，只有关键密钥需要用户自己配

    【字段命名规则】
    - 虽然 .env 里用大写下划线（JWT_SECRET、DATABASE_URL），
      这里用全小写下划线（jwt_secret、database_url），
      pydantic-settings 在读取环境变量时是大小写不敏感的
    """
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",    # 指定 .env 文件路径
        env_file_encoding="utf-8",          # .env 文件编码
        extra="ignore",                     # .env 里多了未定义的字段，忽略不报错
        case_sensitive=False,               # 环境变量名大小写不敏感
    )

    # ──────────── 应用基本信息 ────────────
    app_name: str = "rag-knowledge-base"    # 应用名称，会在 API 文档等地方显示
    log_level: str = "INFO"                # 日志级别：DEBUG/INFO/WARNING/ERROR

    # ──────────── CORS 跨域配置 ────────────
    # .env 里写 "http://localhost:5173,http://example.com"
    # cors_origin_list 属性会把它拆成 ["http://localhost:5173", "http://example.com"]
    #
    # 为什么用 str 而不是 list[str]？
    # pydantic-settings 对 list 类型默认按 JSON 解析（["a","b"]），
    # 但 .env 里用逗号分隔更符合直觉，所以存为 str 然后自己拆分
    cors_origins: str = "http://localhost:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        """把逗号分隔的字符串拆成列表，并去掉空白"""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    # ──────────── 数据库 ────────────
    # asyncpg 是 PostgreSQL 的异步驱动。格式：
    # postgresql+asyncpg://用户名:密码@主机:端口/数据库名
    database_url: str = "postgresql+asyncpg://rag:rag@localhost:5432/rag_kb"

    # ──────────── Redis 配置 ────────────
    # Redis 支持多个「数据库」（db 索引从 0 到 15），
    # 不同用途用不同 db，数据不会互相干扰
    redis_url: str = "redis://localhost:6379/0"         # 应用直接使用（缓存 + 限流）
    celery_broker_url: str = "redis://localhost:6379/1" # Celery 任务消息队列
    celery_result_backend: str = "redis://localhost:6379/2"  # Celery 任务结果存储

    # ──────────── 腾讯云 COS 对象存储 ────────────
    # 文档上传后先存到腾讯云 COS，再异步处理
    cos_secret_id: str = ""     # 腾讯云 API 密钥 ID
    cos_secret_key: str = ""    # 腾讯云 API 密钥 Key
    cos_region: str = "ap-guangzhou"  # COS 地域（广州）
    cos_bucket: str = ""        # COS 存储桶名称

    @property
    def cos_configured(self) -> bool:
        """检查 COS 配置是否完整，三个字段都有值才算配置完成"""
        return bool(self.cos_secret_id and self.cos_secret_key and self.cos_bucket)

    # ──────────── Embedding（文本向量化） ────────────
    # 用 DashScope（阿里云）的 OpenAI 兼容接口
    # 这样可以用 LangChain 的 ChatOpenAI/OpenAIEmbeddings 来调用，不需要用 DashScope 的专用 SDK
    embedding_api_key: str = ""
    embedding_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    embedding_model: str = "text-embedding-v3"
    embedding_dim: int = 1024       # 向量维度
    # 【重要】这个值必须与数据库迁移文件中的 Vector(N) 一致！
    # 如果你改了维度，需要新建数据库迁移，否则会报错
    embedding_batch_size: int = 10  # 批量向量化时，一次处理多少条文本

    # ──────────── 文档上传与切分 ────────────
    upload_max_size_mb: int = 50    # 单个文件最大 50MB
    chunk_size: int = 600           # 每个文本切片的字符数
    chunk_overlap: int = 60         # 相邻切片之间的重叠字符数
    # 【为什么需要重叠？】
    # 如果一刀切下去正好把一个完整的句子/概念切成两半，
    # 重叠区域可以确保关键信息不会被"切丢"

    # ──────────── Chat 模型 ────────────
    # 通义千问的 OpenAI 兼容接口
    chat_api_key: str = ""
    chat_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    chat_model: str = "qwen-plus"   # 通义千问-Plus 模型

    # ──────────── 检索与问答 ────────────
    retrieval_top_k: int = 5        # 最终送给 LLM 的候选取多少条
    retrieval_min_score: float = 0.6   # 相似度阈值：低于此值直接拒答
    chat_history_window: int = 5    # 多轮对话保留最近几轮

    # ──────────── Query 优化（第 5 章） ────────────
    # 用户在问问题时，系统可以先把问题「加工」一下再搜索，
    # 比如改写、分解成多个子问题，或者先生成假设答案再搜索
    query_route_enabled: bool = True        # 是否开启查询路由
    multi_query_count: int = 3              # Multi-Query 生成几个子查询

    # ──────────── 混合检索 ────────────
    retrieval_recall_top_k: int = 20  # 向量检索和全文检索各自召回的条数
    rrf_k: int = 60                   # RRF 融合算法的平滑常数
    # RRF（Reciprocal Rank Fusion）：
    # 把两路检索结果按排名融合，值越小越偏向排名靠前的结果

    # ──────────── Agentic RAG ────────────
    agent_loop_enabled: bool = True   # 是否开启多轮检索循环
    agent_max_rounds: int = 3         # 最多检索几轮

    # ──────────── Reranker（精排） ────────────
    rerank_enabled: bool = True
    rerank_base_url: str = "https://dashscope.aliyuncs.com/compatible-api/v1/reranks"
    rerank_model: str = "qwen3-rerank"
    rerank_api_key: str = ""  # 留空则复用 chat_api_key
    rerank_min_score: float = 0.3     # 精排后低于此值拒答
    rerank_timeout: float = 8.0       # 精排超时（秒）

    # ──────────── 答案校验 ────────────
    verify_answer_enabled: bool = True  # 是否验证答案是否基于引用

    # ──────────── LangSmith 可观测性 ────────────
    langsmith_tracing: bool = False
    langsmith_api_key: str = ""
    langsmith_project: str = "rag-knowledge-base"
    langsmith_endpoint: str = "https://api.smith.langchain.com"
    langsmith_run_url_prefix: str = ""

    # ──────────── 认证 ────────────
    jwt_secret: str = ""              # JWT 签名密钥（必须配置！）
    jwt_algorithm: str = "HS256"      # 签名算法
    jwt_expire_minutes: int = 1440    # Token 过期时间（24 小时）

    default_admin_username: str = "admin"   # 首次启动创建的默认管理员账号
    default_admin_password: str = "admin"
    default_admin_display_name: str = "管理员"

    # ──────────── 语义缓存（第 12 章） ────────────
    semantic_cache_enabled: bool = True
    semantic_cache_ttl_seconds: int = 3600      # 缓存过期时间（1 小时）
    semantic_cache_min_similarity: float = 0.92 # 语义相似度阈值

    # ──────────── 滑动窗口限流（第 12 章） ────────────
    rate_limit_enabled: bool = True
    rate_limit_per_minute: int = 60  # 单用户每分钟最大请求数

    # ──────────── 便捷属性 ────────────
    @property
    def effective_rerank_api_key(self) -> str:
        """如果没单独配 rerank 的 key，就用 chat 的 key（都是 DashScope）"""
        return self.rerank_api_key or self.chat_api_key

    @property
    def observability_enabled(self) -> bool:
        """LangSmith 生效需要同时满足：开关打开 + key 已配置"""
        return bool(self.langsmith_tracing and self.langsmith_api_key)


# 使用 lru_cache 保证全局只有一个 Settings 实例
# 【为什么需要单例？】
# 如果每个模块都 new 一个 Settings()，就会多次读取 .env 文件，
# 而且修改一个地方的 settings 不会同步到其他地方
@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


# 模块加载时立即创建，其他文件直接 import 这个实例使用
# 即：from app.core.config import settings
settings = get_settings()
