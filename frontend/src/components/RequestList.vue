<template>
  <section class="panel list">
    <div class="list-head">
      <div class="list-title">
        <h2>网络请求</h2>
        <label>
          <input v-model="store.onlyApi" type="checkbox" />
          只看接口请求
        </label>
      </div>
      <div class="batch-actions">
        <button class="batch-check" @click="toggleVisibleSelection">
          {{ allPagedSelected ? "取消本页选择" : "选择本页请求" }}
        </button>
        <span class="selected-count">已选 {{ selectedCount }} 条</span>
      </div>
      <div class="export-format-grid" :class="{ disabled: !selectedCount }">
        <button
          v-for="format in exportFormats"
          :key="format.value"
          class="export-format-card"
          :disabled="!selectedCount || exportingFormat === format.value"
          @click="exportSelected(format)"
        >
          <span class="export-icon" :class="format.value">{{ format.icon }}</span>
          <span>
            <strong>{{ format.label }}</strong>
            <small>{{ format.description }}</small>
          </span>
        </button>
      </div>
      <input v-model="store.keyword" class="search" placeholder="搜索 URL / 参数 / 状态码，新网页采集会重置 NEW 标记" />
    </div>

    <div class="requests" @scroll="handleScroll">
      <div
        v-for="request in pagedRequests"
        :key="request.id"
        class="request"
        :class="{ active: store.selectedRequest?.id === request.id }"
        role="button"
        tabindex="0"
        @click="$emit('select-request', request.id)"
        @keydown.enter="$emit('select-request', request.id)"
        @keydown.space.prevent="$emit('select-request', request.id)"
      >
        <label class="request-check-wrap" title="选择该请求" @click.stop>
          <input
            class="request-check"
            type="checkbox"
            :checked="store.selectedRequestIds.has(request.id)"
            @change.stop="toggleRequestSelection(request.id)"
          />
          <span class="request-check-visual"></span>
        </label>
        <span class="method" :class="request.method.toLowerCase()">{{ request.method }}</span>
        <span class="request-main">
          <strong>{{ request.path }}</strong>
          <small>{{ request.resource_type }} · {{ request.duration_ms || "-" }}ms · {{ request.domain }}</small>
        </span>
        <span :class="statusClass(request.status_code)">{{ request.status_code || "-" }}</span>
        <span v-if="request.is_new" class="new-mark">NEW</span>
      </div>

      <button v-if="canLoadMore" class="load-more" @click="loadMore">继续加载更多请求</button>

      <div v-if="visibleRequests.length === 0" class="empty-state">
        暂无请求记录。启动浏览器后，在页面中操作即可看到新增接口。
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, ref, watch } from "vue";
import { captureStore as store } from "../stores/captureStore";
import { api } from "../api/client";
import { statusClass } from "../utils/format";
import { getLatestRequestsByPath } from "../utils/requestStats";

defineEmits(["select-request"]);

const pageSize = 30;
const visibleCount = ref(pageSize);
const exportingFormat = ref("");
const exportFormats = [
  {
    value: "openapi",
    label: "OpenAPI/Swagger",
    description: "导入 Swagger、Apifox",
    icon: "API",
  },
  {
    value: "postman",
    label: "Postman",
    description: "Collection v2.1",
    icon: "PM",
  },
  {
    value: "curl",
    label: "cURL",
    description: "批量命令文本",
    icon: "cURL",
  },
  {
    value: "apifox",
    label: "Apifox",
    description: "Apifox 导入优化",
    icon: "AFX",
  },
];

const filteredRequests = computed(() => {
  // 前端做轻量二次过滤，后端仍支持同样筛选，便于后续大数据量分页优化。
  const keyword = store.keyword.trim().toLowerCase();
  return store.requests.filter((item) => {
    const methodMatched = store.method === "ALL" || item.method === store.method || (store.method === "PUT" && item.method === "PATCH");
    const keywordMatched = !keyword || item.url.toLowerCase().includes(keyword) || String(item.status_code || "").includes(keyword);
    const apiMatched = !store.onlyApi || item.is_api;
    return methodMatched && keywordMatched && apiMatched;
  });
});

const visibleRequests = computed(() => {
  // 重复请求路径只展示最新一条，避免轮询或页面重复请求把列表刷得很乱。
  return getLatestRequestsByPath(filteredRequests.value);
});

const pagedRequests = computed(() => visibleRequests.value.slice(0, visibleCount.value));
const canLoadMore = computed(() => visibleCount.value < visibleRequests.value.length);
const selectedCount = computed(() => store.selectedRequestIds.size);
const allPagedSelected = computed(() => {
  return pagedRequests.value.length > 0 && pagedRequests.value.every((request) => store.selectedRequestIds.has(request.id));
});

watch(
  () => [store.keyword, store.method, store.onlyApi, store.requests.length],
  () => {
    visibleCount.value = pageSize;
  },
);

function loadMore() {
  // 滑动加载每次追加一小批，减少大量请求一次渲染造成的卡顿。
  visibleCount.value = Math.min(visibleCount.value + pageSize, visibleRequests.value.length);
}

function handleScroll(event) {
  const element = event.currentTarget;
  if (element.scrollTop + element.clientHeight >= element.scrollHeight - 80 && canLoadMore.value) {
    loadMore();
  }
}

function toggleRequestSelection(id) {
  // Set 在 reactive 中可直接追踪 size 和 has，这里只维护用户勾选状态。
  if (store.selectedRequestIds.has(id)) {
    store.selectedRequestIds.delete(id);
  } else {
    store.selectedRequestIds.add(id);
  }
}

function toggleVisibleSelection() {
  // 本页选择只作用于当前已加载列表，避免用户误选隐藏在筛选外的大量请求。
  if (allPagedSelected.value) {
    pagedRequests.value.forEach((request) => store.selectedRequestIds.delete(request.id));
    return;
  }
  pagedRequests.value.forEach((request) => store.selectedRequestIds.add(request.id));
}

async function exportSelected(format) {
  // 按用户选择的目标格式批量导出，请求选择逻辑保持统一，便于后续继续扩展导出类型。
  const requestIds = Array.from(store.selectedRequestIds);
  if (!requestIds.length) {
    store.error = "请先勾选需要导出的请求。";
    return;
  }
  exportingFormat.value = format.value;
  try {
    const result = await api.exportRequests(requestIds, format.value);
    downloadExportFile(result);
    store.notice = `已导出 ${requestIds.length} 条请求：${format.label}。`;
  } catch (error) {
    store.error = error.message || "批量导出文件失败，请稍后重试。";
  } finally {
    exportingFormat.value = "";
  }
}

function downloadExportFile(result) {
  // 使用浏览器 Blob 下载导出文件；JSON 自动格式化，cURL 文本保持原样。
  const isJson = String(result.content_type || "").includes("json") || typeof result.data !== "string";
  const content = isJson ? JSON.stringify(result.data, null, 2) : result.data;
  const blob = new Blob([content], { type: result.content_type || "application/octet-stream" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = result.filename || "requests_export.json";
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
</script>
