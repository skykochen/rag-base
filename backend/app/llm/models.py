"""
==========================================
  Chat 模型客户端 —— 通义千问
==========================================

【为什么单独一个文件？】
项目中多处需要调用 Chat 模型（问答、改写、路由、校验），
如果每个地方都 new 一个 ChatOpenAI，会创建多个 HTTP 连接池。
这里统一管理，全局共用同一个实例。

【三次降级设计】
temperature=0 的原因：
- 知识库问答是事实性任务，不是创意写作
- temperature=0 保证输出最确定、最可预测
- 引用编号 [N] 不会在不同 chunk 间漂移
"""

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from app.core.config import settings
from app.core.exceptions import ConfigurationError

_chat_model: BaseChatModel | None = None


def get_chat_model() -> BaseChatModel:
    """
    获取全局唯一的 ChatOpenAI 实例（流式）。

    - 启动时不检查 API key，首次调用时才检查
    - 这样即使没配 key，应用仍能启动（只是问答功能不可用）
    - 单例模式：模型客户端持有 HTTP 连接池，避免重复创建
    """
    global _chat_model
    if _chat_model is not None:
        return _chat_model

    if not settings.chat_api_key:
        raise ConfigurationError("Chat API key 未配置，请在 .env 设置 CHAT_API_KEY")

    _chat_model = ChatOpenAI(
        model=settings.chat_model,       # qwen-plus
        api_key=settings.chat_api_key,    # DashScope API key
        base_url=settings.chat_base_url,  # DashScope OpenAI 兼容端点
        temperature=0,                    # 事实性任务，温度设 0
        streaming=True,                   # 流式输出
    )
    return _chat_model
