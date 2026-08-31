"""
==========================================
  Embedding 客户端 —— 把文本转成向量
==========================================

【什么是 Embedding？】
Embedding（向量化）是把文本变成一串浮点数的过程。
比如"你好"可能变成 [0.1, -0.3, 0.5, ...]（1024 个数字）。
语义相近的文本，它们的向量也相近。

【本项目的 Embedding 模型】
用 DashScope（阿里云）的 text-embedding-v3 模型，
通过 OpenAI 兼容协议调用，所以这里用 LangChain 的 OpenAIEmbeddings。

【为什么不用 DashScope 的专用 SDK？】
- OpenAI 兼容协议已成为行业标准
- 用 OpenAIEmbeddings 可以随时切换底层模型（换成 OpenAI 的 text-embedding-3 等）
- 减少对特定云厂商的依赖
"""

from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings

from app.core.config import settings
from app.core.exceptions import ConfigurationError

# 模块级缓存 Embeddings 实例（单例模式）
_embeddings: Embeddings | None = None


def get_embeddings() -> Embeddings:
    """
    获取 Embeddings 实例（全局单例）。

    如果 API key 未配置，会在启动后首次调用时抛 ConfigurationError，
    而不是在启动时就报错——这样即使没配 embedding，应用仍能启动。
    """
    global _embeddings
    if _embeddings is not None:
        return _embeddings

    if not settings.embedding_api_key:
        raise ConfigurationError("Embedding API key 未配置，请在 .env 设置 EMBEDDING_API_KEY")

    _embeddings = OpenAIEmbeddings(
        model=settings.embedding_model,           # text-embedding-v3
        api_key=settings.embedding_api_key,        # DashScope API key
        base_url=settings.embedding_base_url,      # DashScope OpenAI 兼容端点
        dimensions=settings.embedding_dim,         # 向量维度（1024）
        chunk_size=settings.embedding_batch_size,  # 每批处理多少条（10）
        check_embedding_ctx_length=False,          # 不检查上下文长度（DashScope 没这个限制）
    )
    return _embeddings
