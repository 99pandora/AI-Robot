"""飞书 WebSocket 长连接与 Agent 的业务适配。"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from concurrent.futures import CancelledError as FutureCancelledError
from concurrent.futures import Future
from dataclasses import dataclass
import logging
import threading
from time import monotonic
from typing import Any, Callable
from uuid import NAMESPACE_URL, uuid5

from backend.agent.service import AgentService
from backend.feishu.models import FeishuConnectionStatus, FeishuSettings

logger = logging.getLogger(__name__)

FRIENDLY_FALLBACK = "小苏暂时无法处理这条消息，请稍后重试。"


@dataclass(frozen=True)
class FeishuInboundMessage:
    """从 SDK 归一化对象中提取出的跨线程安全消息快照。"""

    message_id: str
    user_id: str
    chat_id: str
    text: str
    thread_id: str | None = None

    @property
    def conversation_id(self) -> str:
        """群聊话题单独隔离上下文，普通私聊/群聊使用 chat_id。"""

        if self.thread_id:
            return f"{self.chat_id}:{self.thread_id}"
        return self.chat_id

    @property
    def memory_key(self) -> str:
        return f"feishu:{self.user_id}:{self.conversation_id}"


class MessageIdDeduplicator:
    """进程内、线程安全、有界 TTL 消息去重缓存。"""

    def __init__(self, *, ttl_seconds: int, max_entries: int) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._entries: OrderedDict[str, float] = OrderedDict()
        self._lock = threading.RLock()

    def claim(self, message_id: str) -> bool:
        """首次声明消息返回 True，重复消息返回 False。"""

        now = monotonic()
        with self._lock:
            expires_at = self._entries.get(message_id)
            if expires_at is not None and expires_at > now:
                self._entries.move_to_end(message_id)
                return False
            self._entries[message_id] = now + self.ttl_seconds
            self._entries.move_to_end(message_id)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)
            return True

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


ChannelFactory = Callable[[FeishuSettings], Any]


def build_feishu_channel(settings: FeishuSettings) -> Any:
    """构建官方 SDK Channel，并显式配置有限重试和内存去重。"""

    from lark_channel import (
        DedupConfig,
        FeishuChannel,
        InboundConfig,
        OutboundConfig,
        PolicyConfig,
        RetryConfig,
        SafetyConfig,
    )

    return FeishuChannel(
        app_id=settings.app_id,
        app_secret=settings.app_secret,
        transport="ws",
        # 群聊只响应 @机器人，私聊正常响应；SDK 同时过滤机器人自发消息。
        policy=PolicyConfig(require_mention=True),
        inbound=InboundConfig(drop_self_sent=True),
        safety=SafetyConfig(
            dedup=DedupConfig(
                enabled=True,
                ttl_seconds=settings.dedup_ttl_seconds,
                max_entries=settings.dedup_max_entries,
            )
        ),
        # 外层适配器负责发送重试，SDK 单次发送避免产生双重指数重试。
        outbound=OutboundConfig(retry=RetryConfig(max_attempts=1, base_delay_ms=0)),
    )


class FeishuAdapter:
    """将飞书消息桥接到 AgentService，并管理 Channel 生命周期。"""

    def __init__(
        self,
        agent: AgentService,
        settings: FeishuSettings,
        *,
        channel_factory: ChannelFactory = build_feishu_channel,
    ) -> None:
        self.agent = agent
        self.settings = settings
        self._channel_factory = channel_factory
        self._channel: Any | None = None
        self._app_loop: asyncio.AbstractEventLoop | None = None
        self._startup_task: asyncio.Task[None] | None = None
        self._stop_requested = False
        self._status_lock = threading.RLock()
        self._status = (
            FeishuConnectionStatus.STOPPED
            if settings.configured
            else (
                FeishuConnectionStatus.MISCONFIGURED
                if settings.configuration_error
                else FeishuConnectionStatus.DISABLED
            )
        )
        self._last_error: str | None = settings.configuration_error
        self._deduplicator = MessageIdDeduplicator(
            ttl_seconds=settings.dedup_ttl_seconds,
            max_entries=settings.dedup_max_entries,
        )
        self._inflight: set[Future[Any]] = set()
        self._inflight_lock = threading.RLock()
        self._subscriptions: list[Callable[[], Any]] = []

    async def start(self) -> None:
        """启动 SDK 长连接；未配置凭据时不阻断 Web 服务启动。"""

        if not self.settings.configured:
            if self.settings.configuration_error:
                self._set_status(
                    FeishuConnectionStatus.MISCONFIGURED,
                    self.settings.configuration_error,
                )
                logger.error("Feishu is misconfigured: %s", self.settings.configuration_error)
            else:
                self._set_status(FeishuConnectionStatus.DISABLED, None)
            return
        if self._startup_task and not self._startup_task.done():
            return

        self._app_loop = asyncio.get_running_loop()
        self._stop_requested = False
        self._set_status(FeishuConnectionStatus.STARTING, None)
        try:
            # lark-channel-sdk 的底层 WS 模块会在首次导入时绑定一个事件循环。
            # 放到无运行 loop 的 worker 线程构造，避免绑定 FastAPI 主 loop。
            self._channel = await asyncio.to_thread(self._channel_factory, self.settings)
            self._register_handlers(self._channel)
        except Exception as error:
            self._set_status(FeishuConnectionStatus.FAILED, _error_text(error))
            logger.exception("Feishu channel initialization failed")
            return
        self._startup_task = asyncio.create_task(
            self._connect_channel(), name="xiaosu-feishu-connect"
        )

    async def wait_for_startup(self, timeout: float | None = None) -> None:
        """等待一次连接尝试结束，主要用于本地验收和测试。"""

        task = self._startup_task
        if task is not None:
            await asyncio.wait_for(asyncio.shield(task), timeout=timeout)

    async def wait_for_idle(self, timeout: float = 5.0) -> None:
        """等待已接收的消息任务完成，供 IM 场景验收使用。"""

        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            with self._inflight_lock:
                pending = bool(self._inflight)
            if not pending:
                return
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError("等待飞书消息处理完成超时")
            await asyncio.sleep(0.01)

    async def stop(self) -> None:
        """停止连接并尽量等待已接收消息完成。"""

        self._stop_requested = True
        startup_task = self._startup_task
        if startup_task and not startup_task.done():
            startup_task.cancel()
            await asyncio.gather(startup_task, return_exceptions=True)

        with self._inflight_lock:
            pending = list(self._inflight)
        if pending:
            wrapped = [asyncio.wrap_future(item) for item in pending]
            try:
                await asyncio.wait_for(
                    asyncio.gather(*wrapped, return_exceptions=True), timeout=5.0
                )
            except asyncio.TimeoutError:
                for item in pending:
                    item.cancel()

        channel = self._channel
        if channel is not None:
            try:
                stop_background = getattr(channel, "stop_background", None)
                if callable(stop_background):
                    await stop_background()
                else:
                    await channel.disconnect()
            except Exception:
                logger.exception("Feishu channel shutdown failed")
        for unsubscribe in self._subscriptions:
            try:
                unsubscribe()
            except Exception:
                logger.debug("Feishu channel handler unsubscribe failed", exc_info=True)
        self._subscriptions.clear()
        self._channel = None
        self._startup_task = None
        self._deduplicator.clear()
        if self.settings.configured:
            self._set_status(FeishuConnectionStatus.STOPPED, None)
        else:
            self._set_status(FeishuConnectionStatus.DISABLED, None)

    def health(self) -> dict[str, object]:
        """返回健康接口和管理后台可直接展示的连接状态。"""

        with self._status_lock:
            return {
                "status": self._status.value,
                "configured": self.settings.configured,
                "last_error": self._last_error,
            }

    def receive_message(self, message: Any) -> None:
        """供 SDK `message` 事件调用的非阻塞入口。"""

        if self._stop_requested:
            return
        snapshot = _snapshot_message(message)
        if snapshot is None:
            return
        if not self._deduplicator.claim(snapshot.message_id):
            logger.info("Ignore duplicated Feishu message message_id=%s", snapshot.message_id)
            return
        loop = self._app_loop
        if loop is None or loop.is_closed():
            logger.warning("Ignore Feishu message because application loop is unavailable")
            return
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._process_message(snapshot), loop
            )
        except RuntimeError:
            logger.exception("Schedule Feishu message failed message_id=%s", snapshot.message_id)
            return
        with self._inflight_lock:
            self._inflight.add(future)
        future.add_done_callback(self._on_message_done)

    def _register_handlers(self, channel: Any) -> None:
        self._subscriptions.append(channel.on("message", self.receive_message))
        for event, handler in (
            ("reconnecting", self._on_reconnecting),
            ("reconnected", self._on_reconnected),
            ("error", self._on_channel_error),
        ):
            try:
                self._subscriptions.append(channel.on(event, handler))
            except Exception:
                # 生命周期通知是可选能力，不影响消息主链路。
                logger.debug("Feishu channel does not support event=%s", event)

    async def _connect_channel(self) -> None:
        channel = self._channel
        if channel is None:
            return
        try:
            start_background = getattr(channel, "start_background", None)
            if callable(start_background):
                await start_background(timeout=self.settings.connect_timeout_seconds)
            else:
                await channel.connect()
            if not self._stop_requested:
                self._set_status(FeishuConnectionStatus.CONNECTED, None)
                logger.info("Feishu channel connected")
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if not self._stop_requested:
                self._set_status(FeishuConnectionStatus.FAILED, _error_text(error))
                logger.exception("Feishu channel connection failed")

    async def _process_message(self, message: FeishuInboundMessage) -> None:
        answer = ""
        agent_error = ""
        try:
            async for event in self.agent.stream(
                key=message.memory_key,
                message=message.text,
                platform="feishu",
                user_id=message.user_id,
                conversation_id=message.conversation_id,
            ):
                event_name = event.get("event")
                data = event.get("data") or {}
                if event_name == "complete":
                    answer = str(data.get("answer", "")).strip()
                elif event_name == "error":
                    agent_error = str(data.get("message", "")).strip()
        except Exception:
            logger.exception("Feishu Agent processing failed message_id=%s", message.message_id)
            answer = FRIENDLY_FALLBACK

        if agent_error:
            logger.warning(
                "Feishu Agent returned an error message_id=%s error=%s",
                message.message_id,
                agent_error,
            )
            answer = FRIENDLY_FALLBACK
        if not answer:
            answer = FRIENDLY_FALLBACK

        try:
            await self._send_reply_with_retry(message, answer)
        except Exception:
            # 发送失败无法再通过同一消息通道通知用户，至少保留可检索日志。
            logger.exception("Feishu reply failed message_id=%s", message.message_id)

    async def _send_reply_with_retry(
        self, message: FeishuInboundMessage, answer: str
    ) -> None:
        channel = self._channel
        if channel is None:
            raise RuntimeError("Feishu channel is not running")
        options = {
            "reply_to": message.message_id,
            "reply_in_thread": bool(message.thread_id),
            "uuid": str(uuid5(NAMESPACE_URL, f"xiaosu-feishu:{message.message_id}")),
        }
        last_error: Exception | None = None
        for attempt in range(self.settings.send_max_attempts):
            try:
                result = await channel.send(
                    message.chat_id,
                    {"markdown": answer},
                    options,
                )
                if getattr(result, "success", True) is False:
                    raise RuntimeError(_send_result_error(result))
                return
            except Exception as error:
                last_error = error
                logger.warning(
                    "Feishu reply attempt failed message_id=%s attempt=%s/%s error=%s",
                    message.message_id,
                    attempt + 1,
                    self.settings.send_max_attempts,
                    _error_text(error),
                )
                if attempt + 1 < self.settings.send_max_attempts:
                    await asyncio.sleep(self.settings.send_backoff_seconds * (2**attempt))
        raise RuntimeError(_error_text(last_error or RuntimeError("unknown Feishu error")))

    def _on_message_done(self, future: Future[Any]) -> None:
        with self._inflight_lock:
            self._inflight.discard(future)
        try:
            future.result()
        except (asyncio.CancelledError, FutureCancelledError):
            return
        except Exception:
            logger.exception("Unhandled Feishu message task failure")

    def _on_reconnecting(self, *_args: Any) -> None:
        self._set_status(FeishuConnectionStatus.RECONNECTING, None)

    def _on_reconnected(self, *_args: Any) -> None:
        self._set_status(FeishuConnectionStatus.CONNECTED, None)

    def _on_channel_error(self, error: Any = None, *_args: Any) -> None:
        logger.error(
            "Feishu channel error: %s",
            _error_text(error or RuntimeError("unknown error")),
        )

    def _set_status(
        self, status: FeishuConnectionStatus, error: str | None
    ) -> None:
        with self._status_lock:
            self._status = status
            self._last_error = error


def _snapshot_message(message: Any) -> FeishuInboundMessage | None:
    message_id = str(getattr(message, "message_id", None) or getattr(message, "id", "")).strip()
    conversation = getattr(message, "conversation", None)
    chat_id = str(getattr(message, "chat_id", None) or getattr(conversation, "chat_id", "")).strip()
    sender = getattr(message, "sender", None)
    user_id = str(
        getattr(sender, "open_id", None)
        or getattr(sender, "user_id", None)
        or getattr(sender, "union_id", "")
    ).strip()
    sender_type = str(getattr(sender, "sender_type", "") or "").lower()
    if bool(getattr(sender, "is_bot", False)) or sender_type in {"bot", "app"}:
        logger.info("Ignore Feishu bot message message_id=%s", message_id or "unknown")
        return None
    text = str(
        getattr(message, "body_text", None)
        or getattr(message, "safe_content_text", None)
        or getattr(message, "content_text", "")
    ).strip()
    if not message_id or not chat_id or not user_id or not text:
        logger.warning(
            "Ignore incomplete Feishu message message_id=%s chat_id=%s user_id=%s",
            message_id or "unknown",
            chat_id or "unknown",
            user_id or "unknown",
        )
        return None
    thread_id = str(getattr(conversation, "thread_id", "") or "").strip() or None
    return FeishuInboundMessage(
        message_id=message_id,
        user_id=user_id,
        chat_id=chat_id,
        text=text,
        thread_id=thread_id,
    )


def _send_result_error(result: Any) -> str:
    error = getattr(result, "error", None)
    if error is not None:
        return str(error)
    return "Feishu send returned an unsuccessful result"


def _error_text(error: BaseException) -> str:
    text = str(error).strip() or error.__class__.__name__
    return text[:500]
