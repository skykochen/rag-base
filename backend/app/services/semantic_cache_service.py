"""Redis 语义缓存（基于 RedisVL `SemanticCache`）。

设计要点：
- 使用 RedisVL 的 `SemanticCache`，底层落在 Redis Stack 的 RediSearch 向量索引
  （HNSW + 余弦距离）上。查询走 Redis 进程内 KNN，应用层只拿回 Top-1，
  无需把全量缓存条目拉到 Python 端做 cosine
- 权限范围以 sorted+hashed Tag 存入索引：要求请求权限集合与缓存条目权限集合
  「完全一致」，避免「张三的问答被李三命中」造成的越权泄露
- 单条 Hash 自带 TTL，由 Redis 自动过期；过期 / 驱逐策略交给 Redis 配置
"""

import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache

from redisvl.extensions.cache.llm import SemanticCache
from redisvl.query.filter import Tag
from redisvl.utils.vectorize import CustomVectorizer

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_CACHE_NAME = "rag_semantic_cache"
_SCOPE_FIELD = "permission_scope"


@dataclass(frozen=True)
class CachedAnswer:
    """缓存命中后返回给调用方的快照。"""

    answer: str
    citations: list[dict]
    cached_question: str


def _scope_key(permission_scope: list[str]) -> str:
    """把权限集合序列化成「集合相等」可比较的 Tag 值。

    RediSearch Tag 字段天然是「any-of」语义；要表达「集合完全相等」最稳的做法
    是对排序后的权限串做 hash，作为单一 Tag 值存入。这样不同顺序、不同子集
    都会落到不同的 Tag，命中查询天然要求集合完全一致。
    """
    canonical = "\x00".join(sorted(permission_scope))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _stub_embed(text: str, **_: object) -> list[float]:
    """占位 vectorizer：仅用于让 RedisVL 在建索引时知道向量维度。

    主链路始终预先调用项目自己的 embedder 算好 query_embedding，
    再通过 `vector=` 参数直接传给 acheck/astore，永远不会触发到这里。
    """
    return [0.0] * settings.embedding_dim


class SemanticCacheService:
    """问答语义缓存。

    与 RAG 链路解耦：lookup 命中时跳过整个图与 LLM；save 在主链路成功（非拒答）
    后由 ChatService 显式调用。
    """

    def __init__(self) -> None:
        self._cache = SemanticCache(
            name=_CACHE_NAME,
            redis_url=settings.redis_url,
            # RediSearch 用「余弦距离 = 1 - 余弦相似度」做 KNN 排序；阈值同步转换
            distance_threshold=1.0 - settings.semantic_cache_min_similarity,
            ttl=settings.semantic_cache_ttl_seconds,
            # CustomVectorizer 自带 pydantic model_fields，pyright 看不到 __init__
            # 的位置参数；运行时正常，按 RedisVL 文档示例传入 embed 函数即可
            vectorizer=CustomVectorizer(_stub_embed),  # pyright: ignore[reportCallIssue]
            filterable_fields=[{"name": _SCOPE_FIELD, "type": "tag"}],
            overwrite=False,
        )

    async def lookup(
        self,
        query_embedding: list[float],
        permission_scope: list[str],
    ) -> CachedAnswer | None:
        """Redis 内 KNN 查询：相似度阈值 + 权限范围 Tag 同时满足才返回。"""
        scope = _scope_key(permission_scope)
        try:
            hits = await self._cache.acheck(
                vector=query_embedding,
                filter_expression=Tag(_SCOPE_FIELD) == scope,
                num_results=1,
                return_fields=["prompt", "response", "metadata"],
            )
        except Exception:
            logger.exception("semantic cache lookup failed, treat as miss")
            return None

        if not hits:
            return None

        hit = hits[0]
        metadata = hit.get("metadata") or {}
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except json.JSONDecodeError:
                metadata = {}
        logger.info(
            "semantic cache hit: distance=%.4f question=%r",
            float(hit.get("vector_distance", 0.0)),
            hit.get("prompt"),
        )
        return CachedAnswer(
            answer=hit.get("response", ""),
            citations=metadata.get("citations", []),
            cached_question=hit.get("prompt", ""),
        )

    async def save(
        self,
        *,
        question: str,
        query_embedding: list[float],
        answer: str,
        citations: list[dict],
        permission_scope: list[str],
    ) -> None:
        """写入缓存；TTL 由 SemanticCache 自身的 ttl 配置统一控制。"""
        try:
            await self._cache.astore(
                prompt=question,
                response=answer,
                vector=query_embedding,
                metadata={"citations": citations},
                filters={_SCOPE_FIELD: _scope_key(permission_scope)},
            )
        except Exception:
            # 写缓存失败不影响主链路：用户已经拿到答案，缓存只是优化
            logger.exception("semantic cache save failed, skip")


@lru_cache(maxsize=1)
def get_semantic_cache() -> SemanticCacheService:
    return SemanticCacheService()
