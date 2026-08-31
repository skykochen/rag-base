# llm/ 包 —— AI 模型工具层
#
# 这个包封装所有与大语言模型（LLM）交互的代码。
# 项目使用了三个 AI 能力，都通过 DashScope（阿里云）的 OpenAI 兼容协议调用：
#
# 1. Chat 模型（models.py）—— 通义千问 qwen-plus
#    用于：生成回答、改写查询、路由决策、答案校验
#
# 2. Reranker 模型（reranker.py）—— qwen3-rerank
#    用于：对检索结果做精排，把最相关的结果排到前面
#
# 3. Embedding 模型（embedder.py，在 ingestion/ 包中）
#    用于：把文本转成向量，在检索中使用
#
# 【为什么用 OpenAI 兼容协议？】
# DashScope 提供了 OpenAI 兼容的 API 接口，
# 这样可以直接复用 LangChain 的 ChatOpenAI，
# 不需要使用 DashScope 的专用 SDK，切换成本低。
