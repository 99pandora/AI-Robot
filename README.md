# 小苏：公司内部 AI 助手

> 项目状态：已完成第一步工程骨架：FastAPI 主服务、独立 mock API、基础脚本与自动化测试。知识库、Agent、飞书和 Web 管理后台将在后续步骤实现。

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
./scripts/setup.sh
./scripts/start.sh
./scripts/test.sh
./scripts/index.sh
./scripts/build.sh
```

`start.sh` 启动主服务（`GET /api/health`）；`start-mock.sh` 启动独立 mock API（`GET /health`、`GET /api/attendance`、`GET /api/orders`）。mock API 只读取 `data/`，考勤接口的 `user_id` 同时接受 `001` 与 `U001`。

脚本会根据自身位置自动切换到项目根目录，因此在 `scripts/` 目录内直接执行 `./start-mock.sh` 也可以正常启动。

## 会话记忆与日志

Agent 上下文只保存在进程内存中，每个 `platform:user_id:conversation_id` 最多保留最近 4 个用户—助手轮次；服务重启后清空。SQLite 只保存后台审计日志，不会反向恢复 Agent 上下文。

## 飞书接入

飞书采用官方 SDK 长连接接收 `im.message.receive_v1` 事件。需要启用机器人能力、配置事件订阅和消息权限。未配置飞书凭据时，Web 管理后台仍可用于本地知识库和调试聊天。

## 当前限制

- 当前版本不提供后台鉴权，不应直接公开部署。
- 内部业务工具只读取 `attendance.json` 和 `order.json`。
- Embedding 模型变更后需要重新建立 Chroma 索引。

## 开发约束

详细模块边界、接口、测试和扩展方式见 [AGENTS.md](./AGENTS.md)。任何新增工具、IM 平台或模型供应商都应先更新类型、测试和 README。
