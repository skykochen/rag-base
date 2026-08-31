"""
==========================================
  统一日志配置 —— 所有模块共用一个 logger
==========================================

【为什么需要统一的日志配置？】
- 没有这个文件：每个文件 import logging 直接用，格式不统一
- 有这个文件：所有日志统一格式【时间 | 级别 | 模块名 | 消息】
- 调试时一眼就能看出日志来自哪个模块

【使用方式】
在任意文件中：
    from app.core.logging import get_logger
    logger = get_logger(__name__)  # __name__ 会自动带上模块名
    logger.info("xxx")
    logger.error("xxx")

【__name__ 是什么？】
- 在 backend/app/core/config.py 中，__name__ 的值是 "app.core.config"
- 日志就会显示这个模块名，方便定位问题
"""

import logging
import sys

from app.core.config import settings

# 日志格式：【时间 | 级别(左对齐8字符) | 模块名 | 消息内容】
_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# 防止 configure_logging 被多次调用
_configured = False


def configure_logging() -> None:
    """
    配置根 logger，应用启动时调用一次。

    【工作原理】
    1. 创建一个输出到 stdout（标准输出）的处理器
    2. 给处理器设置统一的格式
    3. 把处理器挂到根 logger 上
    4. 根 logger 的所有子 logger（各模块的）都会继承这个配置

    【为什么是幂等的？】
    如果 repeat 调用，会重复添加 handler 导致日志重复打印。
    _configured 标志确保只配置一次。
    """
    global _configured
    if _configured:
        return

    # 创建控制台输出处理器
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))

    # 配置根 logger
    root = logging.getLogger()
    root.handlers.clear()  # 清除默认处理器，避免重复
    root.addHandler(handler)
    root.setLevel(settings.log_level.upper())

    # uvicorn（ASGI 服务器）自带日志处理器
    # 它们会创建自己的 logger，我们让它们继承根 logger 的配置
    # 避免 uvicorn 的日志用不同格式显示
    for noisy in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(noisy).handlers.clear()
        logging.getLogger(noisy).propagate = True  # 传播给根 logger

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """
    获取模块级别的 logger。

    参数：
    - name: 通常传入 __name__，即模块的完整路径名

    返回：
    - 一个已配置好格式的 Logger 实例

    示例：
    logger = get_logger(__name__)  # 比如返回的 name 是 "app.core.config"
    logger.info("服务启动")  # 输出: 2024-01-01 12:00:00 | INFO     | app.core.config | 服务启动
    """
    return logging.getLogger(name)
