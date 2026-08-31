"""
==========================================
  LangSmith 可观测性 —— 追踪每次问答的完整链路
==========================================

【LangSmith 是什么？】
LangSmith 是 LangChain 推出的调试平台，可以追踪每次 LLM 调用的：
- 调用了什么模型
- 传入了什么参数（prompt、temperature 等）
- 输出了什么结果
- 花了多长时间

【为什么需要这个文件？】
- 把 LangSmith SDK 的调用细节封装起来
- 业务代码只看到两个函数：configure_observability() 和 get_current_trace_id()
- 如果以后换追踪平台，只需要改这一个文件

【为什么启动时要设置环境变量？】
- LangSmith SDK 内部读的是环境变量（LANGSMITH_TRACING、LANGSMITH_API_KEY 等）
- 不从我们的 Settings 对象读
- 所以必须把 settings 里的值同步写到 os.environ
"""

import os

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def configure_observability() -> None:
    """
    把 settings 中的 LangSmith 配置同步到环境变量。

    必须在应用启动时（create_app 中）调用一次。
    如果不调这个函数，LangSmith SDK 读不到配置，就不会上报追踪数据。

    【启用条件】
    - LANGSMITH_TRACING=true（settings.langsmith_tracing=True）
    - LANGSMITH_API_KEY 必须有值（settings.langsmith_api_key 非空）
    两者缺一不可。

    【未启用时的处理】
    强制写 LANGSMITH_TRACING=false，避免 SDK 在缺 key 情况下
    尝试上报 trace 导致报错刷屏。
    """
    if settings.observability_enabled:
        os.environ["LANGSMITH_TRACING"] = "true"
        os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key
        os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
        os.environ["LANGSMITH_ENDPOINT"] = settings.langsmith_endpoint
        logger.info(
            "LangSmith tracing enabled: project=%s endpoint=%s",
            settings.langsmith_project,
            settings.langsmith_endpoint,
        )
    else:
        os.environ["LANGSMITH_TRACING"] = "false"
        logger.info("LangSmith tracing disabled (no LANGSMITH_API_KEY or switch off)")


def get_current_trace_id() -> str | None:
    """
    获取当前 @traceable 上下文中的 trace_id。

    【调用时机】
    这个函数必须在 @traceable 装饰的函数内部调用，
    因为 trace_id 是 LangSmith 通过 Python 上下文（context）传递的。

    【返回值】
    - 启用 LangSmith + 在 @traceable 上下文内：返回 trace_id 字符串
    - 其他情况返回 None（不抛异常）

    【设计原则】
    可观测性是「加分项」，不能因为追踪 SDK 的异常导致主流程报错。
    所以即使获取 trace_id 失败，也会返回 None 而不是抛异常。
    """
    if not settings.observability_enabled:
        return None
    try:
        # 延迟 import（惰性导入）：
        # 未启用 LangSmith 时，连 langsmith 模块都不导入
        # 避免无谓的初始化开销
        from langsmith.run_helpers import get_current_run_tree

        run = get_current_run_tree()
        if run is None:
            return None
        return str(run.trace_id)
    except Exception:
        # 兜底：任何异常都不向上抛，只打 WARNING 日志
        logger.warning("get_current_trace_id 异常，返回 None", exc_info=True)
        return None


def build_trace_url(trace_id: str | None) -> str | None:
    """
    把 trace_id 拼成 LangSmith UI 的可点击链接。

    前端拿到这个 URL 后，用户可以点击跳转到 LangSmith 查看详细追踪信息。

    【前置条件】
    需要在 .env 中配置 LANGSMITH_RUN_URL_PREFIX，例如：
    https://smith.langchain.com/o/xxxx/projects/p/rag-knowledge-base

    这个 URL 包含了组织信息，所以是私有的，未配置时只展示复制按钮。
    """
    if not trace_id or not settings.langsmith_run_url_prefix:
        return None
    return f"{settings.langsmith_run_url_prefix.rstrip('/')}/r/{trace_id}"
