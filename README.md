# 小苏：公司内部 AI 助手

> 项目状态：已完成知识库管理后台、最小 Agent 闭环和对话日志页面；飞书接入仍需配置凭据后单独验收。

小苏面向公司员工提供知识库问答、考勤查询、订单汇总和飞书机器人服务。知识库文件来自 `knowledges/`，内部 mock 系统数据来自 `data/`。

## 目标能力

- 支持 Markdown、TXT、PDF、Word 文档的上传、索引、替换、删除和状态查看。
- 基于 Chroma 的知识库检索，回答时返回文件名、位置和原文摘录。
- 通过 LangGraph 自主选择知识检索、考勤、订单和时间工具。
- 飞书长连接机器人接收消息，并按用户与会话保持最近 4 轮内存记忆。
- Vue 管理后台查看文档、对话日志、工具调用、引用和飞书连接状态。
- SSE 流式调试聊天和结构化错误兜底。

## 目录约定

```text
backend/       FastAPI、LangGraph、Chroma、SQLite、飞书适配器
frontend/      Vue 3 + TypeScript + Vite 管理后台
scripts/       setup/start/test/index/build 脚本
data/          attendance.json、order.json mock 数据（只读）
knowledges/    初始知识库文件（只读种子文件）
docs/          架构图、截图和开发说明
storage/       本地运行时数据库、向量索引、上传文件（不提交）
logs/          运行日志（不提交）
```

## 运行要求

- Python 3.11+，使用 `uv` 管理依赖，虚拟环境固定为 `.venv`。
- Node.js 18+，使用 Corepack 管理 `pnpm`。
- OpenAI 兼容的 Chat Completions、Tool Calling 和 Embedding 服务。
- 飞书企业自建应用（仅在需要 IM 演示时配置）。

## 配置

复制 `.env.example` 为 `.env`，填写模型服务和飞书应用配置。真实 `.env`、API Key、SQLite、Chroma、日志和上传文件均不会提交到 Git。

## 常用命令

当前可通过以下脚本执行：

```bash
bash ./scripts/setup.sh
bash ./scripts/build.sh
bash ./scripts/start.sh
bash ./scripts/start-mock.sh
bash ./scripts/start-frontend.sh
bash ./scripts/test.sh
bash ./scripts/index.sh
```

`start.sh` 启动主服务（`GET /api/health`）；`start-mock.sh` 启动独立 mock API（`GET /health`、`GET /api/attendance`、`GET /api/orders`）。考勤和订单工具依赖 mock API，因此本地联调必须同时运行两个脚本；主服务健康检查中的 `dependencies.mock_api` 可直接确认依赖是否在线。mock API 只读取 `data/`，考勤接口的 `user_id` 同时接受 `001` 与 `U001`。

脚本会根据自身位置自动切换到项目根目录，因此在 `scripts/` 目录内执行 `bash ./start-mock.sh` 也可以正常启动。

管理后台有两种启动方式：开发时先在一个终端执行 `bash ./scripts/start.sh`，再执行 `bash ./scripts/start-frontend.sh`，打开 `http://127.0.0.1:5173/`；需要同源访问时先执行 `bash ./scripts/build.sh`，再执行 `bash ./scripts/start.sh`，打开 `http://127.0.0.1:8000/`。后台支持文档列表、文件名搜索、状态筛选、上传、下载、重建索引和停用文档，并在左侧“对话”入口提供 SSE 流式聊天、工具调用状态和知识库引用展示。
`setup.sh`、`build.sh` 和 `start-frontend.sh` 会自动兼容 Git Bash 找不到 `pnpm`、但 Windows `pnpm.cmd` 已安装的情况。

知识库接口包括 `POST/GET /api/documents`、`GET /api/documents/{id}/download`、`POST /api/documents/{id}/reindex` 和 `DELETE /api/documents/{id}`。文档加载优先使用 LangChain 官方 `TextLoader`、`PyPDFLoader` 和 `Docx2txtLoader`，切分使用 `RecursiveCharacterTextSplitter`（最大 150 字符、重叠 30 字符），统一转换成文档对象后再索引；上传同名且 SHA-256 相同的文件会跳过索引，上传同名不同内容会创建新版本。执行 `bash ./scripts/index.sh` 会索引 `knowledges/` 下的种子文档，删除种子只停用索引，不会删除原文件。

路径说明：`backend/knowledge/routes.py` 中的 `APIRouter(prefix="/documents")` 是模块级相对前缀，`backend/main.py` 通过 `include_router(..., prefix="/api")` 再追加服务级前缀，因此最终接口路径是 `/api/documents`（复数）。

Chroma Embedding 使用 LangChain `OpenAIEmbeddings`，支持 OpenAI 兼容服务；运行索引前需要在 `.env` 配置 `EMBEDDING_MODEL` 和对应的 API Key。`EMBEDDING_API_KEY`、`EMBEDDING_BASE_URL` 未填写时会回退到 `LLM_API_KEY`、`LLM_BASE_URL`。
阿里百炼可使用兼容模式配置：`EMBEDDING_BASE_URL=https://<workspace>.cn-beijing.maas.aliyuncs.com/compatible-mode/v1`、`EMBEDDING_MODEL=qwen3.7-text-embedding`。代码关闭了 LangChain 默认的整数 token 输入转换，向该接口直接发送字符串数组；知识库切片上限为 150 字符，因此不会因此放大请求长度。
未配置 Embedding 时主服务仍可启动并提供健康检查，但上传、重建索引和知识库检索会返回配置错误。

## 会话记忆与日志

Agent 使用 LangGraph 的模型—工具循环，工具由模型 Tool Calling 自主选择。聊天接口为 `POST /api/chat/stream`，请求体示例：

```json
{
  "message": "公司年假怎么申请？",
  "platform": "web",
  "user_id": "U001",
  "conversation_id": "demo"
}
```

响应是 SSE，包含 `token`、`tool_call`、`reference`、`complete` 和 `error` 事件；`tool_call.status` 为 `started`、`completed` 或 `failed`。知识库工具使用 LangChain Chroma Retriever 的 MMR，固定 `fetch_k=5`、`k=3`；制度问题没有检索证据时会拒答。考勤和订单工具通过 `MOCK_API_BASE_URL` 调用独立 mock API。

Agent 上下文只保存在 LangChain `InMemoryChatMessageHistory` 中，每个 `platform:user_id:conversation_id` 最多保留最近 4 个用户—助手轮次；服务重启后清空。SQLite 只保存后台审计日志，不会反向恢复 Agent 上下文。

## 飞书接入

飞书采用官方 SDK 长连接接收 `im.message.receive_v1` 事件。需要启用机器人能力、配置事件订阅和消息权限。未配置飞书凭据时，Web 管理后台仍可用于本地知识库和调试聊天。

## 当前限制

- 当前版本不提供后台鉴权，不应直接公开部署。
- 内部业务工具只读取 `attendance.json` 和 `order.json`。
- Embedding 模型变更后需要重新建立 Chroma 索引。

## 开发约束

详细模块边界、接口、测试和扩展方式见 [AGENTS.md](./AGENTS.md)。任何新增工具、IM 平台或模型供应商都应先更新类型、测试和 README。

## 对话日志

左侧“对话日志”入口提供会话摘要查询和详情抽屉，支持按关键字、状态筛选，并展示每轮提问、回答、工具调用、知识库引用、错误信息和耗时。

后端通过 `GET /api/conversations` 获取摘要，通过 `GET /api/conversations/{id}` 获取详情。日志写入 `storage/conversations.sqlite3`，只用于审计展示，不会被 Agent 读取为上下文。
