# 这个文件是空的，它的作用只有一个：
# 让 Python 把 backend/app/ 这个目录识别为「包（package）」。
#
# 什么是包？
# - 在 backend/app/main.py 里写 from app.core.config import settings 时，
#   Python 需要知道 app/ 是一个包，才能找到 app/core/ 下面的模块
# - 如果没有 __init__.py，Python 就不允许从该目录导入
#
# 为什么内容为空？
# - 项目采用「每个模块独立导入」的方式，不需要在 __init__.py 里统一导出
# - 保持为空是最简洁的做法，不会引入循环依赖的风险
#
# Python 3.3+ 实际上支持「隐式命名空间包」（没有 __init__.py 也行），
# 但为了兼容性和明确性，项目仍然保留这个空文件。
