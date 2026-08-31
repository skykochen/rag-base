"""
==========================================
  统一错误处理器 —— 把异常转成 HTTP 响应
==========================================

【为什么需要这个文件？】
没有统一处理时：
    try:
        ...
    except NotFoundError:
        return JSONResponse(status_code=404, content={"code": "not_found", ...})
    except PermissionDeniedError:
        return JSONResponse(status_code=403, content={"code": "permission_denied", ...})
    ...

每个接口都要写重复的 try-except，麻烦且容易漏。

有了统一处理：
    # 业务代码直接抛异常
    raise NotFoundError("用户不存在")
    # error_handlers 自动捕获并转成 HTTP 响应

【工作原理】
FastAPI 提供 add_exception_handler 机制：
1. 路由函数抛异常
2. FastAPI 查找匹配的异常处理器
3. 调用对应的处理器函数
4. 处理器返回 JSONResponse

我们不直接暴露 Python 的异常堆栈给前端，
所有错误统一为 {code, message} 格式。
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.exceptions import AppException
from app.core.logging import get_logger

logger = get_logger(__name__)


async def _app_exception_handler(_: Request, exc: AppException) -> JSONResponse:
    """
    业务异常处理器：把 AppException 转成 JSON 响应。

    响应格式：
    {"code": "not_found", "message": "资源不存在"}

    http_status 从异常实例中取，每种异常有自己的状态码。
    """
    return JSONResponse(
        status_code=exc.http_status,
        content={"code": exc.code, "message": exc.message},
    )


async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    未预期的异常兜底处理器。

    【重要】不暴露堆栈给前端，只记录日志。
    前端只看到「服务内部错误」，开发者去日志里看详情。
    """
    logger.exception("unhandled exception at %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"code": "internal_error", "message": "服务内部错误"},
    )


def register_error_handlers(app: FastAPI) -> None:
    """
    注册异常处理器到 FastAPI 应用。

    必须显式调用，因为在 create_app() 中注册。
    type: ignore 是因为 FastAPI 的类型签名与 Python 异常类型有些兼容性问题，
    不影响实际运行。
    """
    app.add_exception_handler(AppException, _app_exception_handler)
    app.add_exception_handler(Exception, _unhandled_exception_handler)
