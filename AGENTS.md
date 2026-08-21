## 技术栈：

前端(html/Vue/js)、后端语言(python)、向量数据库(chroma) 、框架(langchain/langgraph)

**底线（不遵守扣分）**：

- Python 用 **uv** 管理依赖，虚拟环境必须叫 `.venv`，禁止 `pip install`
- Node 用 **pnpm**，禁止 commonjs
- 用 Next.js → **v18+**；用 React → **v19+**；
- 启动 / 测试 / 部署的命令统一放在 `scripts/*.sh`
- 数据结构强类型（Python 用 Pydantic / dataclass）
- 单文件 ≤ 500 行（Python）/ 800 行，单目录 ≤ 8 个文件

## 沟通方式

- 默认中文回复；代码、命令、变量名、文件路径保持英文
- 结论先行，简洁直接，不先铺垫背景
- 不谄媚，不夸"这是个很好的问题"，不以"当然可以"开头
- 给真实判断—方案有问题直接指出，发现更好做法主动说明

## 项目二次开发规范

### 当前目标

实现“ 小苏 ”公司内部 AI 助手 MVP：知识库问答、考勤查询、订单汇总、飞书机器人和 Web 管理后台。

### 技术与目录

- 后端使用 Python、FastAPI、LangGraph、LangChain、Chroma、SQLite；依赖由 `uv` 管理，虚拟环境固定为 `.venv`。
- 前端使用 Vue 3、TypeScript、Vite、Element Plus；依赖由 `pnpm` 管理，不使用 CommonJS。
- `backend/` 保存 API、Agent、知识库、持久化和飞书适配器；`backend/feishu/` 使用官方 `lark-channel-sdk` 负责 WebSocket 长连接；`frontend/` 保存管理后台；`scripts/` 保存启动、测试、索引和构建命令。
- `frontend/` 使用 Vue 3、TypeScript、Vite 和 Element Plus；已接通知识库文档管理、“对话”入口和“对话日志”页面，聊天页面消费 `/api/chat/stream` 的 SSE 事件。
- `data/attendance.json` 与 `data/order.json` 是只读 mock 数据；`knowledges/` 是只读种子知识文件。
- `storage/` 和 `logs/` 只保存运行时数据，不能提交 Git。

### 会话记忆硬约束

- Agent 上下文只允许保存在进程内存中，不使用数据库或外部缓存恢复上下文。
- Key 使用 `platform:user_id:conversation_id`，每个会话最多保留最近 4 个用户—助手轮次。
- 使用线程安全的内存存储和会话锁；服务重启后记忆必须清空。
- 会话历史使用 LangChain `InMemoryChatMessageHistory` 保存，不能改为 SQLite、文件或外部缓存。
- SQLite 只保存对话审计日志，不能被 Agent 当作上下文加载。

### Agent 与工具

- LangGraph 负责模型决策、工具调用、答案整理、引用校验和流式事件。
- 工具固定包含 `search_knowledge`、`query_attendance`、`query_orders`、`current_time`。
- 工具选择必须使用模型 Tool Calling，不按问题关键词硬编码业务分流。
- 公司制度类答案必须带真实知识库引用；检索不到证据时必须拒答，禁止补写事实。
- `search_knowledge` 使用 LangChain Chroma Retriever 的 MMR，固定 `fetch_k=5`、`k=3`。
- `query_attendance` 兼容 `001` 与 `U001`；订单和考勤工具必须通过 HTTP 调用独立 mock API。

### 知识库行为

- 支持 Markdown、TXT、PDF、Word；文档状态为 `pending`、`indexed` 或 `failed`。
- 文档加载优先使用 LangChain 官方 loader，切分使用 `RecursiveCharacterTextSplitter`，`chunk_size=150`、`chunk_overlap=30`。
- Embedding 使用 LangChain `OpenAIEmbeddings`，配置来自 `EMBEDDING_API_KEY`、`EMBEDDING_BASE_URL` 和 `EMBEDDING_MODEL`；切换模型后必须重建 Chroma 索引。
- 使用文件名和 SHA-256 实现同名替换和重复跳过。
- Chroma chunk 元数据必须保存文档、版本、文件名、标题、页码或段落和 chunk 序号。
- 删除种子文件只停用索引，不删除 `knowledges/` 原文件；删除后的文档不能继续参与检索。

### 公共接口

- 文档：`POST/GET /api/documents`、`GET /api/documents/{id}/download`、`POST /api/documents/{id}/reindex`、`DELETE /api/documents/{id}`。
- 问答：`POST /api/chat/stream`，请求体至少包含 `message`，可选 `platform`、`user_id`、`conversation_id`；SSE 事件包含 token、工具调用、引用、完成和错误，工具状态为 `started`、`completed` 或 `failed`。
- 日志：`GET /api/conversations`、`GET /api/conversations/{id}`。
- 设置与健康：`GET /api/settings`、`PUT /api/settings/model`、`GET /api/health`；健康响应中的 `dependencies.mock_api` 表示考勤和订单 mock 服务是否在线，`dependencies.feishu` 表示飞书适配器是否停用、连接中、已连接或失败。
- Mock API：`GET /api/attendance`、`GET /api/orders`、`GET /health`。

### 飞书与错误处理

- 使用官方 `lark-channel-sdk` 的 `FeishuChannel` WebSocket 长连接接收 `im.message.receive_v1`；SDK 内存去重之外，业务适配器按 `message_id` 做线程安全、有界 TTL 幂等。
- 飞书消息按 `feishu:user_id:chat_id[:thread_id]` 与其他平台隔离最近 4 轮记忆；回调只做归一化和投递，Agent 在应用事件循环后台处理。
- LLM、mock API 和飞书发送失败时有限重试，最终向用户返回友好兜底消息，并写入对话审计或服务日志。
- 未配置飞书凭据时允许本地启动，部分凭据配置显示 `misconfigured`；没有真实凭据不能声称 IM 验收完成。

### 工程和 Git

- 启动、测试、索引、构建和飞书适配器离线验收命令必须位于 `scripts/*.sh`。
- 必须提交 `uv.lock`、`pnpm-lock.yaml`、`.env.example`、源码、脚本、`data/`、`knowledges/` 和项目文档。
- 禁止提交 `.env`、密钥、运行数据库、Chroma、日志、上传文件、缓存和构建产物。
- 修改 API、数据类型、记忆策略或工具时，必须同步更新 README、测试和本文件。
- 提交前检查暂存区并展示变更摘要；禁止强推、rebase 或覆盖远端历史。

### 对话日志实现

- `backend/conversations/` 使用 SQLite 记录会话摘要和每轮审计详情，包含状态、工具调用、知识库引用、错误信息和耗时。
- `GET /api/conversations` 与 `GET /api/conversations/{id}` 提供日志列表和详情；Vue 管理后台的“对话日志”页面负责查询和展示。
- 审计日志只用于管理记录，不得作为 Agent 的上下文来源；Agent 记忆仍只保存在进程内 `InMemoryChatMessageHistory`。
- 考勤或订单 mock 服务不可用时，工具调用状态记录为 `failed`，本轮日志状态也记录为 `failed`，但保留模型生成的兜底回答。
