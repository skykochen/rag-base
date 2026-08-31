"""
==========================================
  services 包 —— 业务逻辑层（Service Layer）
==========================================

【为什么需要 Service Layer？】
  路由（routes）只管"HTTP 入参 → 调 Service → 序列化返回"，
  数据访问（repositories）只管"SQL CRUD"，
  业务逻辑（services）在中间做编排：校验规则、事务边界、调外部 API。

【服务列表与用途】
  · auth_service        · 登录校验 + JWT 签发
  · user_service        · 用户 CRUD + 角色分配（admin）
  · role_service        · 角色 CRUD（admin）
  · permission_service  · 权限标签计算（纯函数，不依赖 DB session）
  · document_service    · 文档上传/查询/删除/重试/重新索引 + 触发 Celery 任务
  · chat_service        · 问答：非流式（历史管理） + 流式（SSE 逐 token）+ MCP + 评测
  · evaluation_service  · 评测 run CRUD + 异步执行器
  · semantic_cache      · Redis 语义缓存（RedisVL SemanticCache）

【事务边界】
  CRUD 类 service 在末尾显式 commit；
  流式 chat_service 在 _persist_* 方法里自主管理 session（与请求生命周期解耦）。
  evaluation_service 的异步执行器用独立 session（BackgroundTasks 上下文）。

【异常约定】
  · "不存在"抛 NotFoundError → 路由层翻译为 404
  · "已存在/校验失败"抛 ConflictError / ValidationError → 路由层翻译为 409 / 422
  · "未授权"在 auth 路由层判定 → 抛 UnauthorizedError → 翻译为 401
"""
