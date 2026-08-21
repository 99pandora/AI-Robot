<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import {
  ChatDotRound,
  CircleCheck,
  Clock,
  DocumentCopy,
  Refresh,
  Search,
  WarningFilled,
} from "@element-plus/icons-vue";
import { ElMessage } from "element-plus";
import { getConversation, listConversations } from "../api";
import type {
  ConversationDetail,
  ConversationStatus,
  ConversationSummary,
} from "../types";

defineProps<{ backendOnline: boolean }>();

const logs = ref<ConversationSummary[]>([]);
const loading = ref(false);
const keyword = ref("");
const statusFilter = ref<ConversationStatus | "">("");
const selectedId = ref<string | null>(null);
const detail = ref<ConversationDetail | null>(null);
const detailLoading = ref(false);
const detailVisible = ref(false);

const statusMeta: Record<ConversationStatus, { label: string; type: "success" | "warning" | "danger" }> = {
  running: { label: "处理中", type: "warning" },
  completed: { label: "已完成", type: "success" },
  failed: { label: "失败", type: "danger" },
};

const completedCount = computed(() => logs.value.filter((item) => item.status === "completed").length);
const failedCount = computed(() => logs.value.filter((item) => item.status === "failed").length);

function statusInfo(status: ConversationStatus) {
  return statusMeta[status] ?? statusMeta.running;
}

async function refresh(showMessage = false): Promise<void> {
  loading.value = true;
  try {
    // 列表只读取会话摘要，点击某一行时再请求完整轮次，避免一次加载过多内容。
    logs.value = await listConversations({
      limit: 100,
      keyword: keyword.value,
      status: statusFilter.value || undefined,
    });
    if (showMessage) {
      ElMessage.success("对话日志已刷新");
    }
  } catch (error) {
    ElMessage.error(errorMessage(error, "无法读取对话日志"));
  } finally {
    loading.value = false;
  }
}

async function openDetail(row: ConversationSummary): Promise<void> {
  selectedId.value = row.id;
  detailVisible.value = true;
  detailLoading.value = true;
  detail.value = null;
  try {
    detail.value = await getConversation(row.id);
  } catch (error) {
    detailVisible.value = false;
    ElMessage.error(errorMessage(error, "无法读取会话详情"));
  } finally {
    detailLoading.value = false;
  }
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function formatDuration(value: number): string {
  if (value < 1000) return `${value} ms`;
  return `${(value / 1000).toFixed(1)} s`;
}

function shortText(value: string, maxLength = 70): string {
  return value.length > maxLength ? `${value.slice(0, maxLength)}…` : value;
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

onMounted(() => refresh());
</script>

<template>
  <section class="logs-page">
    <div class="logs-intro">
      <div>
        <p class="page-description">查看 Agent 的提问、回答、工具调用和知识库引用，便于定位失败请求。</p>
        <div class="hint-line">
          <el-icon><DocumentCopy /></el-icon>
          <span>日志只用于审计展示，不会反向写入会话记忆。</span>
        </div>
      </div>
      <div class="logs-stat-line">
        <span>共 {{ logs.length }} 个会话</span>
        <span class="stat-good">{{ completedCount }} 已完成</span>
        <span class="stat-bad" v-if="failedCount">{{ failedCount }} 失败</span>
      </div>
    </div>

    <section class="logs-card">
      <div class="logs-toolbar">
        <div>
          <h2>对话日志</h2>
          <span class="table-count">按最近更新时间倒序</span>
        </div>
        <div class="filters">
          <el-input
            v-model="keyword"
            clearable
            placeholder="搜索问题、用户或会话 ID"
            class="keyword-input"
            @keyup.enter="refresh()"
          >
            <template #prefix><el-icon><Search /></el-icon></template>
          </el-input>
          <el-select v-model="statusFilter" clearable placeholder="全部状态" class="status-select">
            <el-option label="处理中" value="running" />
            <el-option label="已完成" value="completed" />
            <el-option label="失败" value="failed" />
          </el-select>
          <el-button :loading="loading" @click="refresh(true)">
            <el-icon><Refresh /></el-icon>
            查询
          </el-button>
        </div>
      </div>

      <el-table v-loading="loading" :data="logs" row-key="id" class="logs-table" @row-click="openDetail">
        <el-table-column label="最近问题" min-width="330">
          <template #default="{ row }">
            <div class="question-cell">
              <div class="question-icon"><ChatDotRound /></div>
              <div>
                <div class="question-text">{{ shortText(row.last_question || "（空问题）") }}</div>
                <div class="question-meta">{{ row.platform }} · {{ row.user_id }} · {{ row.conversation_id }}</div>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="105">
          <template #default="{ row }">
            <el-tag :type="statusInfo(row.status).type" effect="light">
              {{ statusInfo(row.status).label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="轮次" width="80">
          <template #default="{ row }">{{ row.turn_count }}</template>
        </el-table-column>
        <el-table-column label="工具 / 引用" width="125">
          <template #default="{ row }">
            <span class="metric-text">{{ row.tool_count }} / {{ row.reference_count }}</span>
          </template>
        </el-table-column>
        <el-table-column label="最近更新" width="150">
          <template #default="{ row }">{{ formatDate(row.updated_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="95" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click.stop="openDetail(row)">查看详情</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无对话日志" :image-size="90">
            <el-button type="primary" @click="refresh(true)">重新查询</el-button>
          </el-empty>
        </template>
      </el-table>
    </section>
  </section>

  <el-drawer v-model="detailVisible" title="会话详情" size="570px" destroy-on-close>
    <div v-loading="detailLoading" class="detail-panel">
      <template v-if="detail">
        <div class="detail-summary">
          <div class="detail-title-row">
            <div>
              <div class="detail-question">{{ shortText(detail.last_question, 110) }}</div>
              <div class="detail-meta">{{ detail.platform }} · {{ detail.user_id }} · {{ detail.conversation_id }}</div>
            </div>
            <el-tag :type="statusInfo(detail.status).type" effect="light">
              {{ statusInfo(detail.status).label }}
            </el-tag>
          </div>
          <div class="detail-metrics">
            <span><strong>{{ detail.turn_count }}</strong> 轮对话</span>
            <span><strong>{{ detail.tool_count }}</strong> 次工具</span>
            <span><strong>{{ detail.reference_count }}</strong> 条引用</span>
            <span><strong>{{ formatDuration(detail.total_duration_ms) }}</strong> 总耗时</span>
          </div>
        </div>

        <div class="turn-list">
          <article v-for="turn in detail.turns" :key="turn.id" class="turn-card">
            <div class="turn-header">
              <span>第 {{ turn.turn_index }} 轮</span>
              <span>{{ formatDate(turn.created_at) }} · {{ formatDuration(turn.duration_ms) }}</span>
            </div>
            <div class="turn-message turn-message--user">
              <div class="turn-label">用户</div>
              <div>{{ turn.user_message }}</div>
            </div>
            <div v-if="turn.assistant_message" class="turn-message turn-message--assistant">
              <div class="turn-label">Agent</div>
              <div class="assistant-content">{{ turn.assistant_message }}</div>
            </div>
            <div v-if="turn.error" class="turn-error">
              <el-icon><WarningFilled /></el-icon>
              <span>{{ turn.error }}</span>
            </div>
            <div v-if="turn.tool_calls.length" class="turn-extra">
              <div class="extra-label"><el-icon><Clock /></el-icon> 工具调用</div>
              <el-tag
                v-for="(tool, toolIndex) in turn.tool_calls"
                :key="`${turn.id}-tool-${toolIndex}`"
                :type="tool.status === 'failed' ? 'danger' : tool.status === 'completed' ? 'success' : 'warning'"
                size="small"
                effect="plain"
              >
                {{ tool.name }} · {{ tool.status === "completed" ? "完成" : tool.status === "failed" ? "失败" : "处理中" }}
              </el-tag>
            </div>
            <div v-if="turn.references.length" class="turn-extra">
              <div class="extra-label"><el-icon><CircleCheck /></el-icon> 知识库引用</div>
              <div v-for="reference in turn.references" :key="`${turn.id}-${reference.filename}-${reference.location}`" class="reference-item">
                <span class="reference-name">{{ reference.filename }}</span>
                <span>{{ reference.location }} · {{ reference.title }}</span>
              </div>
            </div>
          </article>
        </div>
      </template>
    </div>
  </el-drawer>
</template>

<style scoped>
.logs-page { width: 100%; }
.logs-intro { display: flex; align-items: flex-end; justify-content: space-between; margin-bottom: 26px; }
.page-description { margin: 0 0 8px; color: #546662; font-size: 14px; }
.hint-line { display: flex; align-items: center; gap: 6px; color: #7c8d88; font-size: 12px; }
.hint-line .el-icon { color: #0f766e; }
.logs-stat-line { display: flex; gap: 13px; color: #899994; font-size: 12px; }
.stat-good { color: #15803d; }
.stat-bad { color: #be123c; }
.logs-card { overflow: hidden; background: #fff; border: 1px solid #e3ebe7; border-radius: 15px; box-shadow: 0 10px 30px rgba(32, 61, 53, 0.04); }
.logs-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 21px 23px 17px; border-bottom: 1px solid #edf1ef; }
.logs-toolbar h2 { display: inline; margin: 0; color: #29423b; font-size: 16px; }
.table-count { margin-left: 9px; color: #9aa8a3; font-size: 11px; }
.filters { display: flex; gap: 9px; }
.keyword-input { width: 220px; }
.status-select { width: 116px; }
.logs-table { width: 100%; cursor: pointer; }
.question-cell { display: flex; align-items: center; gap: 11px; }
.question-icon { display: grid; width: 34px; height: 34px; place-items: center; color: #0f766e; background: #e8f8f4; border-radius: 9px; }
.question-text { max-width: 430px; overflow: hidden; color: #29423b; font-size: 13px; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.question-meta { max-width: 430px; margin-top: 3px; overflow: hidden; color: #9aa8a3; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.metric-text { color: #5f716b; font-size: 12px; }
.detail-panel { min-height: 100%; }
.detail-summary { padding-bottom: 18px; border-bottom: 1px solid #edf1ef; }
.detail-title-row { display: flex; align-items: flex-start; justify-content: space-between; gap: 15px; }
.detail-question { color: #29423b; font-size: 15px; font-weight: 600; line-height: 1.5; }
.detail-meta { margin-top: 6px; color: #9aa8a3; font-size: 11px; }
.detail-metrics { display: flex; flex-wrap: wrap; gap: 14px; margin-top: 17px; color: #8b9994; font-size: 11px; }
.detail-metrics strong { color: #29423b; font-size: 14px; }
.turn-list { display: flex; flex-direction: column; gap: 13px; padding-top: 18px; }
.turn-card { padding: 14px; border: 1px solid #e5ece9; border-radius: 11px; background: #fbfdfc; }
.turn-header { display: flex; justify-content: space-between; margin-bottom: 11px; color: #93a19d; font-size: 11px; }
.turn-message { padding: 10px 11px; border-radius: 8px; color: #455953; font-size: 13px; line-height: 1.6; white-space: pre-wrap; }
.turn-message--user { background: #edf8f5; }
.turn-message--assistant { margin-top: 8px; background: #f4f6f5; }
.turn-label { margin-bottom: 4px; color: #0f766e; font-size: 11px; font-weight: 600; }
.assistant-content { color: #344a44; }
.turn-error { display: flex; align-items: flex-start; gap: 6px; margin-top: 9px; padding: 8px 10px; color: #be123c; font-size: 12px; background: #fff1f2; border-radius: 7px; }
.turn-extra { margin-top: 11px; }
.extra-label { display: flex; align-items: center; gap: 5px; margin-bottom: 6px; color: #7b8d87; font-size: 11px; }
.reference-item { display: flex; gap: 6px; padding: 5px 0; color: #8b9994; font-size: 11px; }
.reference-name { color: #0f766e; font-weight: 600; }
@media (max-width: 850px) {
  .logs-intro, .logs-toolbar { align-items: flex-start; flex-direction: column; }
  .filters { width: 100%; flex-wrap: wrap; }
  .keyword-input { flex: 1; width: auto; min-width: 200px; }
}
</style>
