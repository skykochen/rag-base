"""
==========================================
  ORM 基类 —— 所有模型的共同祖先
==========================================

【什么是 ORM？】
ORM（Object-Relational Mapping）让你用 Python 对象来操作数据库：
- Python 类 = 数据库表（如 User 类对应 users 表）
- 类的属性 = 表的字段（如 User.username 对应 username 列）
- 类的实例 = 表中的一行记录

【这个文件的作用】
所有 models.py 中定义的类都继承 Base，
这样 SQLAlchemy 知道它们都是数据库模型。

【为什么需要 DeclarativeBase？】
- Base.metadata 记录了所有模型的定义
- alembic 通过对比 Base.metadata 和实际数据库来生成迁移脚本
- 如果模型没有继承 Base，alembic 检测不到它
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """
    SQLAlchemy 2.0 声明式基类。

    所有 ORM 模型都继承这个类：
        class User(Base):
            __tablename__ = "users"
            id = Column(...)

    【2.0 版本的写法变化】
    旧版本（1.x）用 declarative_base() 函数创建基类。
    新版本（2.0）推荐用 DeclarativeBase 类继承，写法更 Pythonic。
    """
    pass
