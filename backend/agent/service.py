"""Agent 编排、会话记忆和 SSE 事件生成。"""

import asyncio
import json
import logging
import os
import time
from collections.abc import AsyncIterator
from typing import Any

from dotenv import load_dotenv
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_openai import ChatOpenAI

from backend.agent.graph import build_graph
from backend.agent.memory import ConversationMemory
from backend.conversations.store import ConversationAuditStore, ConversationTurnHandle
from backend.knowledge.service import DocumentService

logger = logging.getLogger(__name__)


class AgentService:
    """封装模型配置、LangGraph 执行和会话级串行化。"""

    def __init__(
        self,
        knowledge: DocumentService,
        *,
        model: BaseChatModel | None = None,
        audit_store: ConversationAuditStore | None = None,
    ) -> None:
        self.knowledge = knowledge
        self.memory = ConversationMemory(max_turns=4)
        self._model = model
        # SQLite 仅用于后台审计展示，不参与 Agent 上下文恢复。
        self.audit_store = audit_store

    def _chat_model(self) -> BaseChatModel:
        """按需创建 ChatOpenAI，避免未配置密钥时阻塞主服务启动。"""
        if self._model is not None:
            return self._model
        load_dotenv(self.knowledge.settings.project_root / ".env", override=False)
        model_name = os.getenv("LLM_MODEL", "").strip()
        api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
        if not model_name or not api_key:
            raise RuntimeError("LLM_MODEL 和 LLM_API_KEY 尚未配置")
        self._model = ChatOpenAI(
            model=model_name,
            api_key=api_key,
            base_url=os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL"),
            temperature=0,
            streaming=True,
            max_retries=1,
        )
        return self._model

    async def stream(
        self,
        *,
        key: str,
        message: str,
        platform: str = "web",
        user_id: str = "anonymous",
        conversation_id: str = "default",
    ) -> AsyncIterator[dict[str, Any]]:
        async with self.memory.session_lock(key):
            started_at = time.perf_counter()
            audit_handle = self._start_audit(
                platform=platform,
                user_id=user_id,
                conversation_id=conversation_id,
                message=message,
            )
            # 只把上一轮用户问题和最终答案放回上下文，工具中间消息不进入长期记忆。
            previous = self.memory.messages(key)
            state = {"messages": [*previous, HumanMessage(content=message)]}
            answer_parts: list[str] = []
            references: list[dict[str, Any]] = []
            tool_calls: list[dict[str, str]] = []
            tool_failures: list[str] = []
            try:
                graph = build_graph(self._chat_model(), self.knowledge)
            except asyncio.CancelledError:
                # 浏览器主动停止流式输出时也要结束 running 审计记录。
                self._fail_audit(
                    audit_handle,
                    error="请求已取消",
                    tool_calls=tool_calls,
                    references=references,
                    started_at=started_at,
                )
                raise
            except Exception as error:
                logger.exception("agent initialization failed")
                friendly_message = _friendly_error(error)
                self._fail_audit(
                    audit_handle,
                    error=friendly_message,
                    tool_calls=tool_calls,
                    references=references,
                    started_at=started_at,
                )
                yield {"event": "error", "data": {"message": friendly_message}}
                return

            try:
                async for event in graph.astream_events(state, version="v2"):
                    event_name = event.get("event")
                    if event_name == "on_chat_model_stream":
                        # ChatOpenAI 流式输出的文本片段逐个转成 token 事件。
                        text = _chunk_text(event.get("data", {}).get("chunk"))
                        if text:
                            answer_parts.append(text)
                            yield {"event": "token", "data": {"text": text}}
                    elif event_name == "on_tool_start":
                        tool_name = str(event.get("name", "")) or "unknown"
                        tool_calls.append({"name": tool_name, "status": "started"})
                        yield {
                            "event": "tool_call",
                            "data": {"name": tool_name, "status": "started"},
                        }
                    elif event_name == "on_tool_end":
                        # search_knowledge 的工具结果中携带引用，转发给前端展示。
                        output = event.get("data", {}).get("output")
                        tool_data = _tool_output(output)
                        tool_name = str(event.get("name", "")) or "unknown"
                        tool_error = _tool_error_message(tool_name, tool_data)
                        tool_status = "failed" if tool_error else "completed"
                        if tool_error:
                            tool_failures.append(tool_error)
                        _complete_tool_call(tool_calls, tool_name, tool_status)
                        if tool_data.get("references"):
                            for reference in tool_data["references"]:
                                if reference not in references:
                                    references.append(reference)
                                    yield {"event": "reference", "data": reference}
                        tool_event = {
                            "name": tool_name,
                            "status": tool_status,
                        }
                        if tool_error:
                            tool_event["error"] = tool_error
                        yield {
                            "event": "tool_call",
                            "data": tool_event,
                        }
                    elif event_name == "on_chat_model_end" and not answer_parts:
                        text = _message_text(event.get("data", {}).get("output"))
                        if text:
                            answer_parts.append(text)
                            yield {"event": "token", "data": {"text": text}}
            except asyncio.CancelledError:
                # 浏览器主动停止流式输出时也要结束 running 审计记录。
                self._fail_audit(
                    audit_handle,
                    error="请求已取消",
                    tool_calls=tool_calls,
                    references=references,
                    started_at=started_at,
                )
                raise
            except Exception as error:
                logger.exception("agent execution failed")
                friendly_message = _friendly_error(error)
                self._fail_audit(
                    audit_handle,
                    error=friendly_message,
                    tool_calls=tool_calls,
                    references=references,
                    started_at=started_at,
                )
                yield {"event": "error", "data": {"message": friendly_message}}
                return

            answer = "".join(answer_parts).strip()
            if not answer:
                answer = "暂时无法生成回答，请稍后重试。"
                yield {"event": "token", "data": {"text": answer}}
            self.memory.append(key, message, answer)
            if tool_failures:
                # 工具失败但模型仍生成了兜底回答时，仍将本轮标记为失败，便于日志定位。
                self._fail_audit(
                    audit_handle,
                    error="；".join(dict.fromkeys(tool_failures)),
                    answer=answer,
                    tool_calls=tool_calls,
                    references=references,
                    started_at=started_at,
                )
            else:
                self._finish_audit(
                    audit_handle,
                    answer=answer,
                    tool_calls=tool_calls,
                    references=references,
                    started_at=started_at,
                )
            complete_data: dict[str, Any] = {"answer": answer, "references": references}
            if tool_failures:
                complete_data["status"] = "failed"
                complete_data["error"] = "；".join(dict.fromkeys(tool_failures))
            yield {
                "event": "complete",
                "data": complete_data,
            }

    def _start_audit(
        self,
        *,
        platform: str,
        user_id: str,
        conversation_id: str,
        message: str,
    ) -> ConversationTurnHandle | None:
        """审计写入失败不能阻断正常问答，因此这里采用降级策略。"""
        if self.audit_store is None:
            return None
        try:
            return self.audit_store.start_turn(
                platform=platform,
                user_id=user_id,
                conversation_id=conversation_id,
                user_message=message,
            )
        except Exception:
            logger.exception("conversation audit start failed")
            return None

    def _finish_audit(
        self,
        handle: ConversationTurnHandle | None,
        *,
        answer: str,
        tool_calls: list[dict[str, str]],
        references: list[dict[str, Any]],
        started_at: float,
    ) -> None:
        if handle is None or self.audit_store is None:
            return
        try:
            self.audit_store.finish_turn(
                handle,
                answer=answer,
                tool_calls=tool_calls,
                references=references,
                duration_ms=_duration_ms(started_at),
            )
        except Exception:
            logger.exception("conversation audit finish failed")

    def _fail_audit(
        self,
        handle: ConversationTurnHandle | None,
        *,
        error: str,
        answer: str = "",
        tool_calls: list[dict[str, str]],
        references: list[dict[str, Any]],
        started_at: float,
    ) -> None:
        if handle is None or self.audit_store is None:
            return
        try:
            self.audit_store.fail_turn(
                handle,
                error=error,
                answer=answer,
                tool_calls=tool_calls,
                references=references,
                duration_ms=_duration_ms(started_at),
            )
        except Exception:
            logger.exception("conversation audit failure write failed")


def _chunk_text(chunk: Any) -> str:
    """从 LangChain 消息块中提取文本，兼容字符串和多模态内容块。"""
    if isinstance(chunk, AIMessage):
        return _content_text(chunk.content)
    return _content_text(getattr(chunk, "content", ""))


def _message_text(message: Any) -> str:
    """提取非流式模型结束事件中的完整答案文本。"""
    return _content_text(getattr(message, "content", ""))


def _content_text(content: Any) -> str:
    """统一处理 LangChain 可能返回的字符串或内容块列表。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "") if isinstance(part, dict) else str(part) for part in content
        )
    return str(content or "")


def _tool_output(output: Any) -> dict[str, Any]:
    """把工具消息中的 JSON 字符串安全转换为字典。"""
    if isinstance(output, str):
        try:
            value = json.loads(output)
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}
    if isinstance(output, dict):
        return output
    content = getattr(output, "content", "")
    return _tool_output(content)


def _complete_tool_call(tool_calls: list[dict[str, str]], name: str, status: str) -> None:
    """将最近一次同名工具调用从 started 更新为最终状态。"""
    for item in reversed(tool_calls):
        if item["name"] == name and item["status"] == "started":
            item["status"] = status
            return
    # 某些 LangChain 版本可能只发出结束事件，仍要保留审计记录。
    tool_calls.append({"name": name, "status": status})


def _tool_error_message(tool_name: str, tool_data: dict[str, Any]) -> str:
    """把工具返回的内部错误码转换成管理端可读的中文提示。"""
    error_code = str(tool_data.get("error", "")).strip()
    if not error_code:
        return ""
    if error_code == "mock_api_unavailable":
        if tool_name == "query_attendance":
            return "考勤数据服务暂时不可用，请确认 mock API 已启动"
        if tool_name == "query_orders":
            return "订单数据服务暂时不可用，请确认 mock API 已启动"
        return "业务数据服务暂时不可用，请确认 mock API 已启动"
    if error_code == "knowledge_search_unavailable":
        return "知识库检索暂时不可用，请检查 Embedding 配置"
    return f"{tool_name} 调用失败"


def _duration_ms(started_at: float) -> int:
    return max(0, int((time.perf_counter() - started_at) * 1000))


def _friendly_error(error: Exception) -> str:
    """将内部异常转换成不暴露密钥和堆栈的用户提示。"""
    if isinstance(error, RuntimeError):
        return str(error)
    return "Agent 暂时不可用，请稍后重试。"
