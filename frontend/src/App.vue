<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import {
  Check,
  ChatDotRound,
  Delete,
  Document,
  Download,
  FolderOpened,
  Plus,
  Refresh,
  RefreshRight,
  Setting,
  UploadFilled,
  WarningFilled,
} from "@element-plus/icons-vue";
import {
  deleteDocument,
  downloadUrl,
  getHealth,
  listDocuments,
  reindexDocument,
  uploadDocument,
} from "./api";
import type { DocumentRecord, DocumentStatus, FeishuConnectionStatus } from "./types";
import type { UploadFile, UploadUserFile } from "element-plus";
import { ElMessage, ElMessageBox } from "element-plus";
import ChatPanel from "./components/ChatPanel.vue";
import ConversationLogs from "./components/ConversationLogs.vue";

const documents = ref<DocumentRecord[]>([]);
const loading = ref(false);
const uploading = ref(false);
const uploadDialogVisible = ref(false);
const selectedFile = ref<File | null>(null);
const uploadFileList = ref<UploadUserFile[]>([]);
const searchText = ref("");
const statusFilter = ref<DocumentStatus | "">("");
const activeOperation = ref<string | null>(null);
const backendOnline = ref(false);
const mockApiOnline = ref(false);
const feishuStatus = ref<FeishuConnectionStatus>("disabled");
const activeView = ref<"knowledge" | "chat" | "logs">("knowledge");
let healthTimer: ReturnType<typeof setInterval> | null = null;

const filteredDocuments = computed(() => {
  const keyword = searchText.value.trim().toLowerCase();
  return documents.value.filter((document) => {
    const matchesKeyword = !keyword || document.filename.toLowerCase().includes(keyword);
    const matchesStatus = !statusFilter.value || document.status === statusFilter.value;
    return matchesKeyword && matchesStatus;
  });
});

const statistics = computed(() => ({
  total: documents.value.length,
  indexed: documents.value.filter((document) => document.status === "indexed").length,
  pending: documents.value.filter((document) => document.status === "pending").length,
  failed: documents.value.filter((document) => document.status === "failed").length,
}));

const statusMeta: Record<DocumentStatus, { label: string; type: "success" | "warning" | "danger" }> = {
  indexed: { label: "已索引", type: "success" },
  pending: { label: "处理中", type: "warning" },
  failed: { label: "失败", type: "danger" },
};

function statusInfo(status: unknown): { label: string; type: "success" | "warning" | "danger" } {
  return statusMeta[status as DocumentStatus] ?? statusMeta.pending;
}

async function refreshDocuments(showMessage = false): Promise<void> {
  loading.value = true;
  try {
    documents.value = await listDocuments();
    if (showMessage) {
      ElMessage.success("知识库列表已刷新");
    }
  } catch (error) {
    ElMessage.error(errorMessage(error, "无法读取知识库列表"));
  } finally {
    loading.value = false;
  }
}

async function checkBackend(): Promise<void> {
  try {
    const health = await getHealth();
    backendOnline.value = true;
    mockApiOnline.value = health.dependencies?.mock_api === "ok";
    const status = health.dependencies?.feishu?.status;
    feishuStatus.value = isFeishuStatus(status) ? status : "disabled";
  } catch {
    backendOnline.value = false;
    mockApiOnline.value = false;
    feishuStatus.value = "stopped";
  }
}

function isFeishuStatus(status: string | undefined): status is FeishuConnectionStatus {
  return [
    "disabled",
    "stopped",
    "starting",
    "connected",
    "reconnecting",
    "failed",
    "misconfigured",
  ].includes(status ?? "");
}

function feishuStatusLabel(status: FeishuConnectionStatus): string {
  const labels: Record<FeishuConnectionStatus, string> = {
    disabled: "未配置",
    stopped: "未启动",
    starting: "连接中",
    connected: "已连接",
    reconnecting: "重连中",
    failed: "连接失败",
    misconfigured: "配置错误",
  };
  return labels[status];
}

function openUploadDialog(): void {
  selectedFile.value = null;
  uploadFileList.value = [];
  uploadDialogVisible.value = true;
}

function handleFileChange(uploadFile: UploadFile, uploadFiles: UploadFile[]): void {
  const rawFile = uploadFile.raw;
  if (!rawFile) {
    return;
  }
  if (!/\.(md|markdown|txt|pdf|docx)$/i.test(rawFile.name)) {
    ElMessage.warning("仅支持 Markdown、TXT、PDF 和 Word 文件");
    uploadFileList.value = [];
    selectedFile.value = null;
    return;
  }
  selectedFile.value = rawFile;
  uploadFileList.value = uploadFiles.slice(-1) as UploadUserFile[];
}

function handleFileRemove(): void {
  selectedFile.value = null;
  uploadFileList.value = [];
}

async function submitUpload(): Promise<void> {
  if (!selectedFile.value) {
    ElMessage.warning("请先选择一个文档");
    return;
  }
  uploading.value = true;
  try {
    const record = await uploadDocument(selectedFile.value);
    uploadDialogVisible.value = false;
    ElMessage.success(record.skipped ? "内容未变化，已跳过重复索引" : "文档上传并索引成功");
    await refreshDocuments();
  } catch (error) {
    ElMessage.error(errorMessage(error, "文档上传失败"));
  } finally {
    uploading.value = false;
  }
}

function downloadDocument(document: DocumentRecord): void {
  window.open(downloadUrl(document.id), "_blank", "noopener,noreferrer");
}

async function reindex(document: DocumentRecord): Promise<void> {
  activeOperation.value = document.id;
  try {
    await reindexDocument(document.id);
    ElMessage.success(`${document.filename} 已重新索引`);
    await refreshDocuments();
  } catch (error) {
    ElMessage.error(errorMessage(error, "重新索引失败"));
  } finally {
    activeOperation.value = null;
  }
}

async function removeDocument(document: DocumentRecord): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `停用后，${document.filename} 将不再参与知识库检索。种子文件原件不会被删除。`,
      "确认停用文档",
      { type: "warning", confirmButtonText: "确认停用", cancelButtonText: "取消" },
    );
  } catch {
    return;
  }
  activeOperation.value = document.id;
  try {
    await deleteDocument(document.id);
    ElMessage.success("文档已停用");
    await refreshDocuments();
  } catch (error) {
    ElMessage.error(errorMessage(error, "停用文档失败"));
  } finally {
    activeOperation.value = null;
  }
}

function formatSize(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

onMounted(async () => {
  await Promise.all([refreshDocuments(), checkBackend()]);
  healthTimer = setInterval(() => void checkBackend(), 5000);
});

onUnmounted(() => {
  if (healthTimer !== null) {
    clearInterval(healthTimer);
  }
});
</script>

<template>
  <el-container class="app-shell">
    <el-aside class="sidebar" width="238px">
      <div class="brand">
        <div class="brand-mark">苏</div>
        <div>
          <div class="brand-name">小苏</div>
          <div class="brand-caption">内部 AI 助手</div>
        </div>
      </div>

      <div class="sidebar-label">管理中心</div>
      <div class="nav-item" :class="{ 'nav-item--active': activeView === 'chat' }" @click="activeView = 'chat'">
        <el-icon><ChatDotRound /></el-icon>
        <span>对话</span>
        <span class="coming-soon">Agent</span>
      </div>
      <div class="nav-item" :class="{ 'nav-item--active': activeView === 'knowledge' }" @click="activeView = 'knowledge'">
        <el-icon><FolderOpened /></el-icon>
        <span>知识库</span>
        <span class="nav-count">{{ statistics.total }}</span>
      </div>
      <div class="nav-item" :class="{ 'nav-item--active': activeView === 'logs' }" @click="activeView = 'logs'">
        <el-icon><Document /></el-icon>
        <span>对话日志</span>
        <span class="coming-soon">审计</span>
      </div>
      <div class="nav-item nav-item--muted">
        <el-icon><Setting /></el-icon>
        <span>系统设置</span>
        <span class="coming-soon">即将开放</span>
      </div>

      <div class="sidebar-bottom">
        <div class="connection-card">
          <span class="connection-dot" :class="{ 'connection-dot--offline': !backendOnline }"></span>
          <div>
            <div class="connection-title">后端服务</div>
            <div class="connection-status">{{ backendOnline ? "运行正常" : "连接中" }}</div>
          </div>
        </div>
        <div class="connection-card">
          <span class="connection-dot" :class="{ 'connection-dot--offline': feishuStatus !== 'connected' }"></span>
          <div>
            <div class="connection-title">飞书机器人</div>
            <div class="connection-status">{{ feishuStatusLabel(feishuStatus) }}</div>
          </div>
        </div>
        <div class="user-card">
          <div class="avatar">管</div>
          <div>
            <div class="user-name">知识库管理员</div>
            <div class="user-role">Administrator</div>
          </div>
        </div>
      </div>
    </el-aside>

    <el-container>
      <el-header class="topbar">
        <div v-if="activeView === 'knowledge'">
          <div class="breadcrumb">管理中心 <span>/</span> 知识库</div>
          <h1>知识库</h1>
        </div>
        <div v-else-if="activeView === 'chat'">
          <div class="breadcrumb">管理中心 <span>/</span> 对话</div>
          <h1>对话</h1>
        </div>
        <div v-else>
          <div class="breadcrumb">管理中心 <span>/</span> 对话日志</div>
          <h1>对话日志</h1>
        </div>
        <div class="topbar-actions">
          <el-button v-if="activeView !== 'logs'" text @click="activeView = 'logs'">
            <el-icon><Document /></el-icon>
            对话日志
          </el-button>
          <el-button text @click="activeView = activeView === 'knowledge' ? 'chat' : 'knowledge'">
            <el-icon><ChatDotRound v-if="activeView === 'knowledge'" /><FolderOpened v-else /></el-icon>
            {{ activeView === "knowledge" ? "进入对话" : "返回知识库" }}
          </el-button>
          <template v-if="activeView === 'knowledge'">
            <el-button class="refresh-button" :loading="loading" text @click="refreshDocuments(true)">
              <el-icon><Refresh /></el-icon>
              刷新
            </el-button>
            <el-button type="primary" @click="openUploadDialog">
              <el-icon><Plus /></el-icon>
              上传文档
            </el-button>
          </template>
        </div>
      </el-header>

      <el-main class="main-content">
        <ChatPanel
          v-if="activeView === 'chat'"
          :backend-online="backendOnline"
          :mock-api-online="mockApiOnline"
          :feishu-status="feishuStatus"
        />
        <ConversationLogs v-else-if="activeView === 'logs'" :backend-online="backendOnline" />

        <template v-else>
        <section class="intro-row">
          <div>
            <p class="page-description">维护小苏回答问题时使用的制度、手册和业务资料。</p>
            <div class="hint-line">
              <el-icon><Check /></el-icon>
              <span>支持 Markdown、TXT、PDF、Word；同名同内容文件会自动跳过重复索引</span>
            </div>
          </div>
          <div class="updated-note">数据实时来自后端知识库</div>
        </section>

        <section class="stats-grid">
          <div class="stat-card stat-card--teal">
            <div class="stat-icon"><FolderOpened /></div>
            <div><div class="stat-label">文档总数</div><div class="stat-value">{{ statistics.total }}</div></div>
            <div class="stat-foot">当前有效文档</div>
          </div>
          <div class="stat-card stat-card--green">
            <div class="stat-icon"><Check /></div>
            <div><div class="stat-label">已完成索引</div><div class="stat-value">{{ statistics.indexed }}</div></div>
            <div class="stat-foot">可以参与问答</div>
          </div>
          <div class="stat-card stat-card--amber">
            <div class="stat-icon"><RefreshRight /></div>
            <div><div class="stat-label">处理中</div><div class="stat-value">{{ statistics.pending }}</div></div>
            <div class="stat-foot">等待索引完成</div>
          </div>
          <div class="stat-card stat-card--rose">
            <div class="stat-icon"><WarningFilled /></div>
            <div><div class="stat-label">索引失败</div><div class="stat-value">{{ statistics.failed }}</div></div>
            <div class="stat-foot">需要管理员处理</div>
          </div>
        </section>

        <section class="table-card">
          <div class="table-toolbar">
            <div>
              <h2>文档列表</h2>
              <span class="table-count">共 {{ filteredDocuments.length }} 个文档</span>
            </div>
            <div class="filters">
              <el-input v-model="searchText" clearable placeholder="搜索文件名" class="search-input" />
              <el-select v-model="statusFilter" clearable placeholder="全部状态" class="status-select">
                <el-option label="已索引" value="indexed" />
                <el-option label="处理中" value="pending" />
                <el-option label="失败" value="failed" />
              </el-select>
            </div>
          </div>

          <el-table v-loading="loading" :data="filteredDocuments" row-key="id" class="document-table">
            <el-table-column label="文档名称" min-width="280">
              <template #default="{ row }">
                <div class="file-cell">
                  <div class="file-icon"><Document /></div>
                  <div>
                    <div class="file-name">{{ row.filename }}</div>
                    <div class="file-meta">{{ row.is_seed ? "种子文档" : "管理员上传" }} · {{ formatSize(row.size) }}</div>
                  </div>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="120">
              <template #default="{ row }">
                <el-tag :type="statusInfo(row.status).type" effect="light">
                  {{ statusInfo(row.status).label }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="版本" width="80">
              <template #default="{ row }">v{{ row.version }}</template>
            </el-table-column>
            <el-table-column label="切片" width="90">
              <template #default="{ row }">{{ row.chunk_count }}</template>
            </el-table-column>
            <el-table-column label="最近更新" width="150">
              <template #default="{ row }">{{ formatDate(row.updated_at) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="230" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click="downloadDocument(row)">
                  <el-icon><Download /></el-icon>下载
                </el-button>
                <el-button
                  link
                  type="primary"
                  :loading="activeOperation === row.id"
                  @click="reindex(row)"
                >
                  <el-icon><RefreshRight /></el-icon>重建
                </el-button>
                <el-button
                  link
                  type="danger"
                  :loading="activeOperation === row.id"
                  @click="removeDocument(row)"
                >
                  <el-icon><Delete /></el-icon>停用
                </el-button>
              </template>
            </el-table-column>
            <template #empty>
              <el-empty description="还没有符合条件的文档" :image-size="90">
                <el-button type="primary" @click="openUploadDialog">上传第一份文档</el-button>
              </el-empty>
            </template>
          </el-table>
        </section>
        </template>
      </el-main>
    </el-container>
  </el-container>

  <el-dialog v-model="uploadDialogVisible" title="上传知识库文档" width="520px" destroy-on-close>
    <div class="upload-dialog-content">
      <el-alert
        title="上传后会立即解析、切分并调用 Embedding 模型建立索引"
        type="info"
        :closable="false"
        show-icon
      />
      <el-upload
        drag
        :auto-upload="false"
        :limit="1"
        :file-list="uploadFileList"
        :on-change="handleFileChange"
        :on-remove="handleFileRemove"
        :on-exceed="() => ElMessage.warning('一次只能选择一个文档')"
        class="upload-area"
      >
        <el-icon class="upload-icon"><UploadFilled /></el-icon>
        <div class="el-upload__text">将文件拖到这里，或 <em>点击选择</em></div>
        <template #tip>
          <div class="el-upload__tip">支持 .md / .markdown / .txt / .pdf / .docx</div>
        </template>
      </el-upload>
    </div>
    <template #footer>
      <el-button @click="uploadDialogVisible = false">取消</el-button>
      <el-button type="primary" :loading="uploading" @click="submitUpload">开始索引</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.app-shell { min-height: 100vh; }
.sidebar { display: flex; flex-direction: column; padding: 28px 16px 20px; color: #d7e5e1; background: #123c3a; }
.brand { display: flex; align-items: center; gap: 11px; padding: 0 13px 40px; }
.brand-mark { display: grid; width: 38px; height: 38px; place-items: center; color: #115e59; font-size: 19px; font-weight: 800; background: #ccfbf1; border-radius: 12px; }
.brand-name { color: #fff; font-size: 17px; font-weight: 700; letter-spacing: 0.08em; }
.brand-caption { margin-top: 2px; color: #9fc0b9; font-size: 11px; }
.sidebar-label { padding: 0 13px 10px; color: #789d96; font-size: 11px; letter-spacing: 0.12em; }
.nav-item { display: flex; align-items: center; gap: 11px; min-height: 44px; margin: 3px 0; padding: 0 13px; border-radius: 10px; font-size: 13px; cursor: pointer; }
.nav-item--active { color: #e7fffa; background: rgba(153, 246, 228, 0.16); box-shadow: inset 3px 0 #5eead4; }
.nav-item--muted { color: #9fc0b9; }
.nav-item--muted .el-icon { color: #70938d; }
.nav-count { min-width: 23px; margin-left: auto; padding: 1px 6px; color: #b9fff0; font-size: 11px; text-align: center; background: rgba(94, 234, 212, 0.14); border-radius: 8px; }
.coming-soon { margin-left: auto; color: #71918b; font-size: 10px; }
.sidebar-bottom { margin-top: auto; }
.connection-card, .user-card { display: flex; align-items: center; gap: 10px; padding: 13px; border-top: 1px solid rgba(184, 226, 216, 0.12); }
.connection-card { margin-bottom: 4px; }
.connection-dot { width: 8px; height: 8px; background: #5eead4; border-radius: 50%; box-shadow: 0 0 0 4px rgba(94, 234, 212, 0.12); }
.connection-dot--offline { background: #fbbf24; box-shadow: 0 0 0 4px rgba(251, 191, 36, 0.12); }
.connection-title, .user-name { color: #d7e5e1; font-size: 12px; }
.connection-status, .user-role { margin-top: 2px; color: #7fa59d; font-size: 10px; }
.avatar { display: grid; width: 30px; height: 30px; place-items: center; color: #115e59; font-size: 12px; font-weight: 700; background: #a7f3d0; border-radius: 50%; }
.topbar { display: flex; align-items: center; justify-content: space-between; height: 96px; padding: 0 44px; background: rgba(255, 255, 255, 0.72); border-bottom: 1px solid #e5ece9; backdrop-filter: blur(12px); }
.breadcrumb { margin-bottom: 5px; color: #93a19d; font-size: 11px; }
.breadcrumb span { padding: 0 7px; color: #c1cbc8; }
h1 { margin: 0; color: #1d302c; font-size: 24px; letter-spacing: -0.02em; }
.topbar-actions { display: flex; gap: 10px; }
.main-content { max-width: 1480px; width: 100%; margin: 0 auto; padding: 34px 44px 60px; }
.intro-row { display: flex; align-items: flex-end; justify-content: space-between; margin-bottom: 26px; }
.page-description { margin: 0 0 8px; color: #546662; font-size: 14px; }
.hint-line { display: flex; align-items: center; gap: 6px; color: #7c8d88; font-size: 12px; }
.hint-line .el-icon { color: #0f766e; }
.updated-note { color: #9aa8a3; font-size: 11px; }
.stats-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 15px; margin-bottom: 24px; }
.stat-card { position: relative; min-height: 132px; overflow: hidden; padding: 20px; border: 1px solid rgba(211, 224, 220, 0.82); border-radius: 14px; box-shadow: 0 8px 24px rgba(36, 68, 61, 0.04); }
.stat-card::after { position: absolute; right: -22px; bottom: -30px; width: 110px; height: 110px; content: ""; border: 1px solid currentColor; border-radius: 50%; opacity: 0.12; }
.stat-card--teal { color: #0f766e; background: linear-gradient(145deg, #effcf9, #e2f7f2); }
.stat-card--green { color: #15803d; background: linear-gradient(145deg, #f0fdf4, #e3f7e9); }
.stat-card--amber { color: #b45309; background: linear-gradient(145deg, #fffbeb, #fff4d4); }
.stat-card--rose { color: #be123c; background: linear-gradient(145deg, #fff1f2, #ffe4e6); }
.stat-icon { display: grid; width: 31px; height: 31px; place-items: center; margin-bottom: 11px; color: inherit; background: rgba(255, 255, 255, 0.68); border-radius: 9px; }
.stat-label { color: #65736e; font-size: 12px; }
.stat-value { margin-top: 1px; color: #203a34; font-size: 25px; font-weight: 700; }
.stat-foot { position: absolute; right: 20px; bottom: 18px; color: #8a9994; font-size: 11px; }
.table-card { overflow: hidden; background: #fff; border: 1px solid #e3ebe7; border-radius: 15px; box-shadow: 0 10px 30px rgba(32, 61, 53, 0.04); }
.table-toolbar { display: flex; align-items: center; justify-content: space-between; padding: 21px 23px 17px; border-bottom: 1px solid #edf1ef; }
.table-toolbar h2 { display: inline; margin: 0; color: #29423b; font-size: 16px; }
.table-count { margin-left: 9px; color: #9aa8a3; font-size: 11px; }
.filters { display: flex; gap: 9px; }
.search-input { width: 190px; }
.status-select { width: 116px; }
.document-table { width: 100%; }
.file-cell { display: flex; align-items: center; gap: 11px; }
.file-icon { display: grid; width: 34px; height: 34px; place-items: center; color: #0f766e; background: #e8f8f4; border-radius: 9px; }
.file-name { overflow: hidden; max-width: 380px; color: #29423b; font-size: 13px; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.file-meta { margin-top: 2px; color: #9aa8a3; font-size: 11px; }
.upload-dialog-content { padding: 1px 0 4px; }
.upload-area { margin-top: 16px; }
.upload-area :deep(.el-upload-dragger) { padding: 27px 0 23px; border-color: #b9dcd5; background: #f7fcfb; }
.upload-area :deep(.el-upload-dragger:hover) { border-color: #0f766e; }
.upload-icon { margin-bottom: 7px; color: #0f766e; font-size: 30px; }
.upload-area em { color: #0f766e; font-style: normal; }
.upload-area :deep(.el-upload__tip) { color: #9aa8a3; }
@media (max-width: 1080px) {
  .sidebar { width: 205px !important; }
  .topbar, .main-content { padding-right: 28px; padding-left: 28px; }
  .stats-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 720px) {
  .sidebar { display: none; }
  .topbar { height: auto; min-height: 88px; padding: 18px 20px; }
  .topbar-actions .refresh-button { display: none; }
  .main-content { padding: 24px 16px 40px; }
  .intro-row { align-items: flex-start; flex-direction: column; gap: 8px; }
  .updated-note { display: none; }
  .stats-grid { gap: 10px; }
  .stat-card { min-height: 118px; padding: 15px; }
  .stat-foot { right: 15px; bottom: 14px; }
  .table-toolbar { align-items: flex-start; flex-direction: column; gap: 14px; }
  .filters { width: 100%; }
  .search-input, .status-select { flex: 1; width: auto; }
}
</style>
