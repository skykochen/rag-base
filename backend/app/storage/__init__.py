"""
==========================================
  storage 包 —— 文件存储抽象层
==========================================

【为什么需要这一层？】
  · 文档入库需要把原始文件存到某个地方
  · 当前用腾讯云 COS，将来可能换本地磁盘 / AWS S3 / MinIO
  · 通过 FileService 统一封装，切换后端只改这个包

【两层结构】
  · cos_client.py  · CosS3Client 的薄封装（put/get/delete + ping 健康检查）
  · file_service.py · 高层业务接口（upload/download/delete + object key 生成）

【异步适配】
  cos-python-sdk-v5 是同步 SDK，通过 asyncio.to_thread 包成协程。
  后续如果用 aiohttp 重写 COS 调用，接口不换，只是底层变真异步。
"""
