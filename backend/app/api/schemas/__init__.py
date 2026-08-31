# schemas/ 包 —— 请求和响应的数据格式定义
#
# 这个包定义所有 API 接口的"数据格式"。
# 每个文件对应一组相关的接口：
# - auth.py        — 登录请求/响应、用户信息、角色信息
# - chat.py        — 会话创建、消息、流式问答请求
# - documents.py   — 文档信息、切片信息、任务进度
# - evaluations.py — 评测运行、评测结果、Bad Case
# - roles.py       — 角色创建/更新
# - users.py       — 用户创建/更新
#
# 一般使用 Pydantic 模型来定义格式，好处：
# 1. 自动校验前端传入的数据是否符合格式
# 2. 自动生成 OpenAPI 文档（Swagger UI）
# 3. 自动把 ORM 对象转成 JSON 响应
