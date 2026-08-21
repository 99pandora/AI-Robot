"""基于 LangChain 内存历史的进程内会话记忆。"""

import asyncio
from threading import RLock

from langchain_core.chat_history import InMemoryChatMessageHistory
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage


class ConversationMemory:
    """按会话键保存最近四轮用户与助手消息，不落盘、不跨进程共享。"""

    def __init__(self, max_turns: int = 4) -> None:
        self.max_messages = max_turns * 2
        self._histories: dict[str, InMemoryChatMessageHistory] = {}
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._lock = RLock()

    def session_lock(self, key: str) -> asyncio.Lock:
        """返回会话级异步锁，避免同一会话的请求交错写入历史。"""
        with self._lock:
            return self._session_locks.setdefault(key, asyncio.Lock())

    def messages(self, key: str) -> list[BaseMessage]:
        """读取历史快照，调用方不会直接修改内部消息列表。"""
        with self._lock:
            history = self._histories.get(key)
            return list(history.messages) if history else []

    def append(self, key: str, user_message: str, assistant_message: str) -> None:
        """追加一轮对话，并裁剪最早消息以保持四轮上限。"""
        with self._lock:
            history = self._histories.setdefault(key, InMemoryChatMessageHistory())
            history.add_messages(
                [HumanMessage(content=user_message), AIMessage(content=assistant_message)]
            )
            if len(history.messages) > self.max_messages:
                # 一轮始终由 HumanMessage + AIMessage 组成，因此按消息数裁剪不会拆散轮次。
                kept = list(history.messages[-self.max_messages :])
                history.clear()
                history.add_messages(kept)

    def clear(self) -> None:
        """清空所有历史；服务重启时会重新创建该对象。"""
        with self._lock:
            self._histories.clear()
            self._session_locks.clear()
