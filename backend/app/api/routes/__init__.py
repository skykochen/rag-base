# routes/ 包 —— 所有 API 路由定义
#
# 每一个文件对应一组相关的 API 接口：
# - health.py     — 健康检查（数据库、COS 连通性检测）
# - auth.py       — 登录、获取当前用户信息
# - users.py      — 用户管理（admin 专用：增删改查）
# - roles.py      — 角色管理（admin 专用）
# - documents.py  — 文档上传、列表、详情、删除等操作
# - chat.py       — 会话管理 + SSE 流式问答
# - evaluations.py — 自动化评测管理
#
# 【路由文件的设计原则】
# 每个文件只做三件事：
# 1. 定义 URL 路径（@router.get/post/delete/...）
# 2. 接收请求参数
# 3. 调用 Service 层处理，返回响应
# 不包含任何业务逻辑！
