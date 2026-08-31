# repositories/ 包 —— 数据访问层（Repository 模式）
#
# 什么是 Repository 模式？
# 每一个「数据库表」对应一个 Repository 类，专门操作这个表。
# 比如 user_repo.py 只操作 users 表，chunk_repo.py 只操作 document_chunks 表。
#
# 【为什么要有 Repository 层？】
# 想象一下没有 Repository 层的代码：
#   # 业务代码里直接写 SQL
#   result = await session.execute(select(User).where(User.id == id))
#   user = result.scalar_one_or_none()
#
# 这样写的问题：
# 1. 如果 User 表改了字段名（比如 username -> name），所有业务代码都得改
# 2. 如果查询逻辑变得复杂（比如加了权限判断），每个调用处都得改
# 3. 业务代码和 SQL 混杂，难以测试
#
# 有了 Repository 层：
#   user = await user_repo.get_by_id(id)
#   # 无论底层表怎么变，调用处都不需要改
#
# 【核心约定】
# - Repository 只做 CRUD（增删改查），不做业务决策
# - Repository 不负责 commit（提交事务），由 Service 层控制
# - Repository 不负责业务校验，比如"用户是否存在"由 Service 判断
