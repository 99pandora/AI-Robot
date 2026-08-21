<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from "vue";
import {
  ChatDotRound,
  CircleCheck,
  DocumentCopy,
  Loading,
  MagicStick,
  Promotion,
  RefreshRight,
  User,
  VideoPause,
  WarningFilled,
} from "@element-plus/icons-vue";
import { ElMessage } from "element-plus";
import { streamChat } from "../api";
import type {
  ChatEvent,
  ChatMessage,
  ChatReference,
  FeishuConnectionStatus,
  ToolCallEvent,
} from "../types";

const props = defineProps<{
  backendOnline: boolean;
  mockApiOnline: boolean;
  feishuStatus: FeishuConnectionStatus;
}>();

const STORAGE_USER = "xiaosu-chat-user-id";
const STORAGE_CONVERSATION = "xiaosu-chat-conversation-id";
const suggestions = [
  "公司年假怎么申请？",
  "帮我查一下员工 001 最近的考勤",
  "统计一下最近的订单金额",
  "现在几点？",
];

const messages = ref<ChatMessage[]>([]);
const draft = ref("");
const sending = ref(false);
const userId = ref(readStorage(STORAGE_USER, "anonymous"));
const conversationId = ref(readStorage(STORAGE_CONVERSATION, createId()));
const messagesViewport = ref<HTMLElement | null>(null);
const activeController = ref<AbortController | null>(null);

const canSend = computed(() => Boolean(draft.value.trim()) && !sending.value);
const connectionLabel = computed(() => (props.backendOnline ? "服务在线" : "等待后端"));
const feishuLabel = computed(() => {
  const labels: Record<FeishuConnectionStatus, string> = {
    disabled: "飞书未配置",
    stopped: "飞书未启动",
    starting: "飞书连接中",
    connected: "飞书在线",
    reconnecting: "飞书重连中",
    failed: "飞书连接失败",
    misconfigured: "飞书配置错误",
  };
  return labels[props.feishuStatus];
});

function readStorage(key: string, fallback: string): string {
  try {
    return localStorage.getItem(key) || fallback;
  } catch {
    return fallback;
  }
}

function createId(): string {
  return typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
    ? crypto.randomUUID().slice(0, 8)
    : Math.random().toString(36).slice(2, 10);
}

function persistIdentity(): void {
  try {
    localStorage.setItem(STORAGE_USER, userId.value.trim() || "anonymous");
    localStorage.setItem(STORAGE_CONVERSATION, conversationId.value);
  } catch {
    // 隐私模式下 localStorage 可能不可用，不影响当前页面会话。
  }
}

function newConversation(): void {
  // 只清理前端展示并生成新会话 ID，后端记忆会因 key 变化而自然隔离。
  stopGeneration();
  messages.value = [];
  conversationId.value = createId();
  persistIdentity();
  ElMessage.success("已创建新会话");
}

function applySuggestion(suggestion: string): void {
  if (sending.value) return;
  draft.value = suggestion;
}

function handleComposerKeydown(event: KeyboardEvent): void {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    void sendMessage();
  }
}

async function sendMessage(): Promise<void> {
  const content = draft.value.trim();
  if (!content || sending.value) return;

  persistIdentity();
  draft.value = "";
  const userMessage: ChatMessage = {
    id: createId(),
    role: "user",
    content,
    references: [],
    tools: [],
  };
  const assistantMessage: ChatMessage = {
    id: createId(),
    role: "assistant",
    content: "",
    references: [],
    tools: [],
  };
  messages.value.push(userMessage, assistantMessage);
  sending.value = true;
  activeController.value = new AbortController();
  await scrollToBottom();

  try {
    await streamChat(
      {
        message: content,
        platform: "web",
        user_id: userId.value.trim() || "anonymous",
        conversation_id: conversationId.value,
      },
      (event) => handleChatEvent(event, assistantMessage),
      activeController.value.signal,
    );
  } catch (error) {
    if (!isAbortError(error)) {
      assistantMessage.error = errorMessage(error, "聊天请求失败，请稍后重试");
      ElMessage.error(assistantMessage.error);
    }
  } finally {
    sending.value = false;
    activeController.value = null;
    await scrollToBottom();
  }
}

function handleChatEvent(event: ChatEvent, assistant: ChatMessage): void {
  // token、工具状态和引用分开处理，避免完成事件到达前页面没有反馈。
  if (event.event === "token") {
    assistant.content += stringValue(event.data.text);
  } else if (event.event === "tool_call") {
    const status = normalizeToolStatus(event.data.status);
    updateTool(assistant.tools, {
      name: stringValue(event.data.name),
      status,
    });
    if (status === "failed" && event.data.error) {
      assistant.error = stringValue(event.data.error);
    }
  } else if (event.event === "reference") {
    const reference = toReference(event.data);
    if (reference && !assistant.references.some((item) => sameReference(item, reference))) {
      assistant.references.push(reference);
    }
  } else if (event.event === "complete") {
    if (!assistant.content) {
      assistant.content = stringValue(event.data.answer);
    }
    const references = event.data.references;
    if (Array.isArray(references)) {
      references.forEach((item) => {
        const reference = toReference(item);
        if (reference && !assistant.references.some((current) => sameReference(current, reference))) {
          assistant.references.push(reference);
        }
      });
    }
    if (event.data.error) {
      assistant.error = stringValue(event.data.error);
    }
  } else if (event.event === "error") {
    assistant.error = stringValue(event.data.message) || "Agent 暂时不可用";
    if (!assistant.content) {
      assistant.content = assistant.error;
    }
  }
  void scrollToBottom();
}

function normalizeToolStatus(value: unknown): ToolCallEvent["status"] {
  if (value === "completed" || value === "failed") return value;
  return "started";
}

function toolTagType(status: ToolCallEvent["status"]): "info" | "success" | "danger" {
  if (status === "completed") return "success";
  if (status === "failed") return "danger";
  return "info";
}

function toolStatusLabel(status: ToolCallEvent["status"]): string {
  if (status === "completed") return "已完成";
  if (status === "failed") return "失败";
  return "调用中";
}

function renderMessage(content: string): string {
  // 仅转换模型常用的粗体、列表和换行；先转义 HTML，避免 v-html 引入脚本。
  const escaped = content.replace(/[&<>"']/g, (character) => {
    const entities: Record<string, string> = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    };
    return entities[character];
  });
  return escaped
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/^(\s*)[*-]\s+/gm, "$1<span class=\"message-bullet\">•</span> ")
    .replace(/\n/g, "<br />");
}

function updateTool(tools: ToolCallEvent[], next: ToolCallEvent): void {
  const existing = [...tools].reverse().find((tool) => tool.name === next.name);
  if (existing) {
    existing.status = next.status;
  } else {
    tools.push(next);
  }
}

function toReference(value: unknown): ChatReference | null {
  if (!value || typeof value !== "object") return null;
  const item = value as Record<string, unknown>;
  if (!item.filename && !item.text) return null;
  return {
    filename: stringValue(item.filename),
    location: stringValue(item.location),
    title: stringValue(item.title),
    text: stringValue(item.text),
  };
}

function sameReference(left: ChatReference, right: ChatReference): boolean {
  return left.filename === right.filename && left.location === right.location && left.text === right.text;
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value : value == null ? "" : String(value);
}

function stopGeneration(): void {
  // AbortController 会终止浏览器读取，不会影响后端其他会话。
  activeController.value?.abort();
  activeController.value = null;
  sending.value = false;
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

async function scrollToBottom(): Promise<void> {
  await nextTick();
  const viewport = messagesViewport.value;
  if (viewport) {
    viewport.scrollTop = viewport.scrollHeight;
  }
}

onMounted(() => {
  persistIdentity();
});

onUnmounted(() => {
  activeController.value?.abort();
});
</script>

<template>
  <section class="chat-workspace">
    <div class="chat-intro">
      <div>
        <div class="chat-eyebrow"><el-icon><MagicStick /></el-icon> LangGraph Agent</div>
        <h2>和小苏聊聊</h2>
        <p>知识库问答、考勤查询、订单汇总，都可以直接交给小苏处理。</p>
      </div>
      <div class="chat-intro-actions">
        <el-tag :type="props.backendOnline ? 'success' : 'warning'" effect="light">
          <span class="status-dot"></span>{{ connectionLabel }}
        </el-tag>
        <el-tag :type="props.mockApiOnline ? 'success' : 'danger'" effect="light">
          <span class="status-dot"></span>{{ props.mockApiOnline ? "业务数据在线" : "业务数据离线" }}
        </el-tag>
        <el-tag :type="props.feishuStatus === 'connected' ? 'success' : 'info'" effect="light">
          <span class="status-dot"></span>{{ feishuLabel }}
        </el-tag>
        <el-button plain @click="newConversation">
          <el-icon><RefreshRight /></el-icon>新会话
        </el-button>
      </div>
    </div>

    <section class="chat-card">
      <header class="chat-card-header">
        <div class="chat-session-title">
          <div class="chat-avatar"><ChatDotRound /></div>
          <div>
            <strong>小苏</strong>
            <span>当前会话 · {{ conversationId }}</span>
          </div>
        </div>
        <div class="chat-identity">
          <el-icon><User /></el-icon>
          <el-input v-model="userId" size="small" maxlength="128" placeholder="用户 ID" @change="persistIdentity" />
        </div>
      </header>

      <div ref="messagesViewport" class="messages-viewport">
        <div v-if="!messages.length" class="chat-empty">
          <div class="empty-icon"><ChatDotRound /></div>
          <h3>从一个问题开始</h3>
          <p>你可以试试下面的快捷问题，也可以直接输入自己的问题。</p>
          <div class="suggestions">
            <el-button v-for="suggestion in suggestions" :key="suggestion" round plain @click="applySuggestion(suggestion)">
              {{ suggestion }}
            </el-button>
          </div>
        </div>

        <div v-for="message in messages" :key="message.id" class="message-row" :class="`message-row--${message.role}`">
          <div class="message-avatar">
            <User v-if="message.role === 'user'" />
            <MagicStick v-else />
          </div>
          <article class="message-bubble">
            <div class="message-meta">{{ message.role === "user" ? "你" : "小苏" }}</div>
            <div v-if="message.content" class="message-content" v-html="renderMessage(message.content)"></div>
            <div v-else-if="message.role === 'assistant' && sending" class="typing-indicator">
              <i></i><i></i><i></i><span>正在思考</span>
            </div>
            <div v-if="message.error" class="message-error">
              <el-icon><WarningFilled /></el-icon><span>{{ message.error }}</span>
            </div>

            <div v-if="message.tools.length" class="tool-list">
              <el-tag
                v-for="(tool, index) in message.tools"
                :key="`${tool.name}-${index}`"
                :type="toolTagType(tool.status)"
                size="small"
                effect="plain"
                class="tool-tag"
              >
                <el-icon class="tool-status-icon" :class="{ 'tool-status-icon--running': tool.status === 'started' }">
                  <WarningFilled v-if="tool.status === 'failed'" />
                  <CircleCheck v-else-if="tool.status === 'completed'" />
                  <Loading v-else />
                </el-icon>
                <span>{{ tool.name }}</span><span class="tool-separator">·</span><span>{{ toolStatusLabel(tool.status) }}</span>
              </el-tag>
            </div>
            <div v-if="message.references.length" class="reference-list">
              <div class="reference-heading"><DocumentCopy />参考资料</div>
              <details v-for="reference in message.references" :key="`${reference.filename}-${reference.location}-${reference.text}`" class="reference-item">
                <summary>{{ reference.filename }} <span>{{ reference.location }}</span></summary>
                <p>{{ reference.text }}</p>
              </details>
            </div>
          </article>
        </div>
      </div>

      <footer class="composer">
        <el-input
          v-model="draft"
          type="textarea"
          :rows="2"
          resize="none"
          maxlength="4000"
          show-word-limit
          :disabled="sending"
          placeholder="输入你的问题，Enter 发送，Shift + Enter 换行"
          @keydown="handleComposerKeydown"
        />
        <div class="composer-footer">
          <span><el-icon><CircleCheck /></el-icon>回答基于当前知识库和业务工具</span>
          <div>
            <el-button v-if="sending" plain @click="stopGeneration">
              <el-icon><VideoPause /></el-icon>停止
            </el-button>
            <el-button type="primary" :disabled="!canSend" @click="sendMessage">
              发送<el-icon><Promotion /></el-icon>
            </el-button>
          </div>
        </div>
      </footer>
    </section>
  </section>
</template>

<style scoped>
.chat-workspace { display: flex; flex-direction: column; gap: 22px; min-height: calc(100vh - 164px); }
.chat-intro { display: flex; align-items: flex-end; justify-content: space-between; gap: 20px; }
.chat-eyebrow { display: flex; align-items: center; gap: 6px; color: #0f766e; font-size: 12px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; }
.chat-intro h2 { margin: 7px 0 6px; color: #1d302c; font-size: 24px; letter-spacing: -0.03em; }
.chat-intro p { margin: 0; color: #6d7d77; font-size: 13px; }
.chat-intro-actions { display: flex; align-items: center; gap: 10px; }
.status-dot { display: inline-block; width: 6px; height: 6px; margin-right: 5px; vertical-align: middle; background: currentColor; border-radius: 50%; }
.chat-card { display: flex; flex: 1; flex-direction: column; min-height: 610px; overflow: hidden; background: #fff; border: 1px solid #e1ebe7; border-radius: 17px; box-shadow: 0 12px 35px rgba(32, 61, 53, 0.06); }
.chat-card-header { display: flex; align-items: center; justify-content: space-between; gap: 20px; padding: 16px 22px; border-bottom: 1px solid #edf2f0; }
.chat-session-title { display: flex; align-items: center; gap: 11px; }
.chat-avatar { display: grid; width: 34px; height: 34px; place-items: center; color: #0f766e; background: #dff8f1; border-radius: 11px; }
.chat-session-title strong { display: block; color: #29423b; font-size: 13px; }
.chat-session-title span { display: block; margin-top: 3px; color: #98a6a1; font-size: 11px; }
.chat-identity { display: flex; align-items: center; gap: 7px; width: 180px; color: #81918b; }
.messages-viewport { flex: 1; min-height: 380px; max-height: calc(100vh - 405px); overflow-y: auto; padding: 28px clamp(18px, 7vw, 100px); background: linear-gradient(180deg, #fbfdfc, #f7faf8); }
.chat-empty { display: flex; min-height: 380px; flex-direction: column; align-items: center; justify-content: center; color: #667872; text-align: center; }
.empty-icon { display: grid; width: 54px; height: 54px; place-items: center; margin-bottom: 15px; color: #0f766e; font-size: 25px; background: #e3f8f2; border-radius: 18px; }
.chat-empty h3 { margin: 0 0 5px; color: #29423b; font-size: 17px; }
.chat-empty p { margin: 0; font-size: 12px; }
.suggestions { display: flex; flex-wrap: wrap; justify-content: center; gap: 8px; max-width: 650px; margin-top: 22px; }
.suggestions .el-button { height: 32px; color: #477068; border-color: #cce4dd; background: #fff; }
.message-row { display: flex; align-items: flex-start; gap: 10px; max-width: 860px; margin: 0 auto 22px; }
.message-row--user { flex-direction: row-reverse; }
.message-avatar { display: grid; flex: 0 0 28px; width: 28px; height: 28px; place-items: center; margin-top: 20px; color: #55736b; font-size: 14px; background: #e6efec; border-radius: 9px; }
.message-row--user .message-avatar { color: #115e59; background: #c9f3e8; }
.message-bubble { max-width: min(75%, 680px); padding: 12px 15px; border: 1px solid #e5eeeb; border-radius: 4px 14px 14px 14px; background: #fff; box-shadow: 0 4px 14px rgba(37, 72, 62, 0.04); }
.message-row--user .message-bubble { border-color: #0f766e; border-radius: 14px 4px 14px 14px; background: #0f766e; box-shadow: 0 5px 15px rgba(15, 118, 110, 0.16); }
.message-meta { margin-bottom: 5px; color: #8c9b96; font-size: 10px; }
.message-row--user .message-meta { color: #bdece2; text-align: right; }
.message-content { color: #334841; font-size: 13px; line-height: 1.75; white-space: pre-wrap; word-break: break-word; }
.message-content :deep(strong) { color: #203a34; font-weight: 700; }
.message-content :deep(.message-bullet) { display: inline-block; width: 1.1em; color: #0f766e; font-weight: 700; }
.message-row--user .message-content { color: #fff; }
.message-row--user .message-content :deep(strong), .message-row--user .message-content :deep(.message-bullet) { color: inherit; }
.typing-indicator { display: flex; align-items: center; gap: 4px; min-height: 22px; color: #94a49e; font-size: 12px; }
.typing-indicator i { width: 5px; height: 5px; background: #5c978c; border-radius: 50%; animation: typing 1.2s infinite ease-in-out; }
.typing-indicator i:nth-child(2) { animation-delay: 0.15s; }.typing-indicator i:nth-child(3) { animation-delay: 0.3s; }
.typing-indicator span { margin-left: 5px; }
.message-error { display: flex; align-items: flex-start; gap: 6px; margin-top: 10px; padding: 8px 10px; color: #b45309; font-size: 11px; line-height: 1.5; border: 1px solid #f6d9a7; border-radius: 8px; background: #fffaf0; }
.message-error :deep(.el-icon) { flex: 0 0 auto; width: 14px; height: 14px; margin-top: 1px; font-size: 14px; }
.tool-list { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
.tool-list .tool-tag { display: inline-flex; align-items: center; gap: 4px; border-radius: 999px; }
.tool-status-icon { display: inline-flex; flex: 0 0 14px; width: 14px; height: 14px; font-size: 14px; }
.tool-status-icon :deep(svg) { width: 14px; height: 14px; }
.tool-status-icon--running { animation: spin 1s linear infinite; }
.tool-separator { opacity: 0.55; }
.reference-list { margin-top: 13px; padding-top: 11px; border-top: 1px solid #edf2f0; }
.reference-heading { display: flex; align-items: center; gap: 5px; margin-bottom: 6px; color: #0f766e; font-size: 11px; font-weight: 700; }
.reference-item { padding: 7px 9px; color: #58736b; font-size: 11px; border: 1px solid #e2efeb; border-radius: 7px; background: #f8fcfa; }
.reference-item + .reference-item { margin-top: 5px; }
.reference-item summary { cursor: pointer; font-weight: 600; }.reference-item summary span { margin-left: 5px; color: #94a39e; font-weight: 400; }
.reference-item p { margin: 6px 0 0; color: #667b74; line-height: 1.6; }
.composer { padding: 15px 22px 17px; border-top: 1px solid #e8efed; background: #fff; }
.composer :deep(.el-textarea__inner) { padding: 10px 12px; color: #29423b; border-color: #d7e7e2; box-shadow: none; }
.composer :deep(.el-textarea__inner:focus) { border-color: #0f766e; }
.composer-footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: 10px; }
.composer-footer > span { display: flex; align-items: center; gap: 5px; color: #9aa8a3; font-size: 11px; }
.composer-footer > span .el-icon { color: #0f766e; }
.composer-footer > div { display: flex; gap: 8px; }
@keyframes typing { 0%, 60%, 100% { opacity: .35; transform: translateY(0); } 30% { opacity: 1; transform: translateY(-3px); } }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 720px) {
  .chat-intro { align-items: flex-start; flex-direction: column; }.chat-intro-actions { width: 100%; justify-content: space-between; }
  .chat-card { min-height: calc(100vh - 190px); }.chat-card-header { align-items: flex-start; flex-direction: column; padding: 14px 16px; }.chat-identity { width: 100%; }
  .messages-viewport { max-height: none; padding: 22px 12px; }.message-bubble { max-width: 86%; }.composer { padding: 12px; }.composer-footer { align-items: flex-end; flex-direction: column; }
}
</style>
