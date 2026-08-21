"""飞书 IM 适配器的离线验收测试。"""

import asyncio
from types import SimpleNamespace

from backend.feishu.models import FeishuConnectionStatus, FeishuSettings
from backend.feishu.service import (
    FeishuAdapter,
    MessageIdDeduplicator,
    build_feishu_channel,
)


class FakeAgent:
    def __init__(self, *, error: bool = False) -> None:
        self.error = error
        self.calls: list[dict[str, str]] = []

    async def stream(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            yield {"event": "error", "data": {"message": "模拟模型错误"}}
            return
        yield {"event": "token", "data": {"text": "模拟"}}
        yield {
            "event": "complete",
            "data": {"answer": "飞书测试回答"},
        }


class FakeChannel:
    def __init__(self, *, failures: int = 0) -> None:
        self.handlers: dict[str, object] = {}
        self.failures = failures
        self.send_calls: list[tuple[str, object, object]] = []
        self.started = False
        self.stopped = False

    def on(self, event: str, handler):
        self.handlers[event] = handler

        def unsubscribe() -> None:
            self.handlers.pop(event, None)

        return unsubscribe

    async def start_background(self, *, timeout: float) -> None:
        self.started = True

    async def stop_background(self) -> None:
        self.stopped = True

    async def send(self, chat_id: str, message: object, options: object):
        self.send_calls.append((chat_id, message, options))
        if self.failures:
            self.failures -= 1
            raise RuntimeError("模拟发送失败")
        return SimpleNamespace(success=True)

    def emit(self, message: object) -> None:
        handler = self.handlers["message"]
        handler(message)


def _settings(**overrides: object) -> FeishuSettings:
    values = {
        "app_id": "cli_test",
        "app_secret": "secret_test",
        "send_backoff_seconds": 0,
    }
    values.update(overrides)
    return FeishuSettings(**values)


def _message(message_id: str = "om_test", *, user_id: str = "ou_001") -> SimpleNamespace:
    return SimpleNamespace(
        id=message_id,
        body_text="测试消息",
        conversation=SimpleNamespace(chat_id="oc_001", thread_id=None),
        sender=SimpleNamespace(open_id=user_id, is_bot=False, sender_type="user"),
    )


def test_message_id_deduplicator_is_bounded_and_idempotent() -> None:
    deduplicator = MessageIdDeduplicator(ttl_seconds=60, max_entries=2)

    assert deduplicator.claim("m1") is True
    assert deduplicator.claim("m1") is False
    assert deduplicator.claim("m2") is True
    assert deduplicator.claim("m3") is True
    # m1 was evicted by the bounded cache and can be accepted again.
    assert deduplicator.claim("m1") is True


def test_official_channel_uses_websocket_and_finite_sdk_retry() -> None:
    async def scenario() -> None:
        channel = await asyncio.to_thread(build_feishu_channel, _settings())

        assert channel.config.transport.kind == "ws"
        assert channel.config.safety.dedup.enabled is True
        assert channel.config.outbound.retry.max_attempts == 1

        await channel.disconnect()

    asyncio.run(scenario())


def test_feishu_message_is_processed_once_with_isolated_memory() -> None:
    async def scenario() -> None:
        agent = FakeAgent()
        channel = FakeChannel()
        adapter = FeishuAdapter(agent, _settings(), channel_factory=lambda _: channel)

        await adapter.start()
        await adapter.wait_for_startup(timeout=1)
        channel.emit(_message())
        channel.emit(_message())
        await adapter.wait_for_idle()

        assert adapter.health()["status"] == FeishuConnectionStatus.CONNECTED.value
        assert len(agent.calls) == 1
        assert agent.calls[0]["key"] == "feishu:ou_001:oc_001"
        assert len(channel.send_calls) == 1
        assert channel.send_calls[0][0] == "oc_001"
        assert channel.send_calls[0][1] == {"markdown": "飞书测试回答"}
        assert channel.send_calls[0][2]["reply_to"] == "om_test"

        await adapter.stop()
        assert channel.stopped is True

    asyncio.run(scenario())


def test_feishu_reply_retries_and_agent_failure_uses_friendly_fallback() -> None:
    async def scenario() -> None:
        agent = FakeAgent(error=True)
        channel = FakeChannel(failures=2)
        adapter = FeishuAdapter(
            agent,
            _settings(send_max_attempts=3),
            channel_factory=lambda _: channel,
        )

        await adapter.start()
        await adapter.wait_for_startup(timeout=1)
        channel.emit(_message("om_retry"))
        await adapter.wait_for_idle()

        assert len(channel.send_calls) == 3
        assert channel.send_calls[-1][1] == {
            "markdown": "小苏暂时无法处理这条消息，请稍后重试。"
        }
        await adapter.stop()

    asyncio.run(scenario())


def test_feishu_without_credentials_is_disabled() -> None:
    async def scenario() -> None:
        agent = FakeAgent()
        adapter = FeishuAdapter(agent, FeishuSettings())

        await adapter.start()

        assert adapter.health() == {
            "status": "disabled",
            "configured": False,
            "last_error": None,
        }

    asyncio.run(scenario())


def test_feishu_partial_credentials_are_reported_as_misconfigured() -> None:
    async def scenario() -> None:
        adapter = FeishuAdapter(FakeAgent(), FeishuSettings(app_id="cli_only"))

        await adapter.start()

        assert adapter.health()["status"] == FeishuConnectionStatus.MISCONFIGURED.value
        assert "FEISHU_APP_ID" in str(adapter.health()["last_error"])

    asyncio.run(scenario())
