"""
==========================================
  统一异常定义 —— 业务异常的基石
==========================================

【为什么需要自定义异常？】
- Python 内置的 Exception 只能传一个消息字符串
- 我们需要区分「没找到资源」、「没权限」、「参数不对」等不同情况
- 自定义异常可以携带额外的信息（HTTP 状态码、错误码），
  让 API 层能统一捕获并返回合适的 HTTP 响应

【设计思路】
- 所有业务异常继承 AppException
- AppException 定义了 code（业务错误码）、message（错误描述）、http_status（HTTP 状态码）
- api/error_handlers.py 会捕获 AppException，提取这些字段返回给前端

【学习提示】
- 这是很基础但很重要的设计模式：统一的异常层次
- 在其他项目中你也会看到类似的模式，比如继承自 RuntimeError
"""

from http import HTTPStatus


class AppException(Exception):
    """
    业务异常基类。

    所有自定义异常都继承这个类，这样 API 层可以通过一个 except 捕获所有业务异常。

    关键属性：
    - code: str — 业务错误码，给前端用的（如 "not_found"、"unauthorized"）
    - message: str — 人类可读的错误描述
    - http_status: int — HTTP 状态码（404、401、403 等）
    """
    code: str = "internal_error"
    message: str = "服务内部错误"
    http_status: int = HTTPStatus.INTERNAL_SERVER_ERROR  # 默认 500

    def __init__(self, message: str | None = None, *, code: str | None = None) -> None:
        """
        可以传自定义的 message 和 code 覆盖类属性。

        参数：
        - message: 可选的错误描述，覆盖类的默认 message
        - code: 可选的错误码，覆盖类的默认 code

        使用示例：
        raise NotFoundError("用户不存在")
        raise PermissionDeniedError("无权删除该文档", code="cannot_delete")
        """
        if message is not None:
            self.message = message
        if code is not None:
            self.code = code
        # 调用父类 Exception 的初始化，把 message 传给 Exception
        # 这样 str(err) 或 err.args 也能看到错误消息
        super().__init__(self.message)

    def __str__(self) -> str:
        """打印异常时显示 readable 格式，方便调试"""
        return f"[{self.code}] {self.message}"


class NotFoundError(AppException):
    """
    资源不存在（HTTP 404）。

    使用场景：
    - 查询不存在的文档
    - 查询不存在的会话
    - 操作不存在的用户

    前端收到后会展示「资源不存在」的提示
    """
    code = "not_found"
    message = "资源不存在"
    http_status = HTTPStatus.NOT_FOUND


class UnauthorizedError(AppException):
    """
    未认证 / 凭证无效（HTTP 401）。

    使用场景：
    - 未提供 token
    - token 已过期
    - token 被篡改

    【重要】前端收到 401 会清除登录状态并跳转到登录页！
    所以在不需要登录的接口（如登录接口本身）不要抛这个异常。
    """
    code = "unauthorized"
    message = "请先登录"
    http_status = HTTPStatus.UNAUTHORIZED


class PermissionDeniedError(AppException):
    """
    权限不足（HTTP 403）。

    与 UnauthorizedError 的区别：
    - 401：不知道你是谁（没登录）
    - 403：知道你是谁，但权限不够

    使用场景：
    - 普通用户访问管理员接口
    - 用户访问自己没有权限的文档
    """
    code = "permission_denied"
    message = "无权访问该资源"
    http_status = HTTPStatus.FORBIDDEN


class ConfigurationError(AppException):
    """
    服务配置缺失（HTTP 503）。

    使用场景：
    - 数据库连接失败
    - 缺少必要的 API Key
    - 外部服务不可用

    返回 503（Service Unavailable）而不是 500，表示这是配置问题不是代码 bug。
    """
    code = "configuration_error"
    message = "服务配置缺失"
    http_status = HTTPStatus.SERVICE_UNAVAILABLE


class ValidationError(AppException):
    """
    参数校验失败（HTTP 400）。

    使用场景：
    - 文件大小超过限制
    - JSON 请求体缺少必填字段
    - 参数格式不对

    注意：Pydantic 本身的校验错误会返回 422，不需要走这里。
    这个异常用在 Pydantic 无法覆盖的校验场景。
    """
    code = "validation_error"
    message = "参数校验失败"
    http_status = HTTPStatus.BAD_REQUEST


class ConflictError(AppException):
    """
    资源冲突（HTTP 409）。

    使用场景：
    - 重复上传同一份文件（SHA256 相同）
    - 创建已存在的用户名
    - 重复操作
    """
    code = "conflict"
    message = "资源冲突"
    http_status = HTTPStatus.CONFLICT


class RateLimitedError(AppException):
    """
    请求频率过高（HTTP 429）。

    由滑动窗口限流器触发。
    用户短时间内发送太多请求时抛这个异常，提示用户稍后再试。
    """
    code = "rate_limited"
    message = "请求过于频繁，请稍后再试"
    http_status = HTTPStatus.TOO_MANY_REQUESTS
