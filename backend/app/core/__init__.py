# core/ 包 —— 项目核心基础设施
#
# 这个包集中存放「所有模块都可能用到的基础能力」，
# 不包含任何具体的业务逻辑。
#
# 为什么要把这些放一起？
# - config.py：读取 .env 配置，全局只需一份 settings 实例
# - security.py：密码加密和 JWT 令牌，认证模块需要，其他模块也可能需要解码 token
# - exceptions.py：统一异常类，让 API 层能统一捕获并转成 HTTP 错误码
# - logging.py：统一日志格式，避免每个模块自己配一遍
# - observability.py：LangSmith 链路追踪，调试问答链路时用
# - redis.py：Redis 连接池，缓存和限流都用同一个
# - rate_limiter.py：限流逻辑，可被任何写接口复用
#
# 学习提示：
# 这些文件是项目的地基——你不需要一开始就全部理解。
# 建议先看 config.py 了解项目有哪些配置项，
# 然后看 exceptions.py 了解错误怎么传递，
# 用到其他功能时再回来看对应的文件。
