<template>
  <main class="shell" :style="backgroundStyle">
    <div class="ambient-card"></div>
    <section class="app">
      <TopBar
        @start="startCapture"
        @clear-current="clearCurrent"
        @reset-profile="resetBrowserProfile"
        @open-settings="settingsOpen = true"
      />

      <div v-if="store.notice" class="toast success">{{ store.notice }}</div>
      <div v-if="store.error" class="toast error">{{ store.error }}</div>

      <section class="workspace">
        <SidePanel
          @open-settings="settingsOpen = true"
          @quick-background="quickBackground"
        />
        <RequestList @select-request="selectRequest" />
      </section>
    </section>

    <RequestDetail :open="Boolean(store.selectedRequest)" @close="store.selectedRequest = null" />
    <SettingsDrawer :open="settingsOpen" @close="settingsOpen = false" @save="saveSettings" />
  </main>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import TopBar from "./components/TopBar.vue";
import SidePanel from "./components/SidePanel.vue";
import RequestList from "./components/RequestList.vue";
import RequestDetail from "./components/RequestDetail.vue";
import SettingsDrawer from "./components/SettingsDrawer.vue";
import { api } from "./api/client";
import { captureStore as store } from "./stores/captureStore";

const settingsOpen = ref(false);
let pollTimer = null;
let syncing = false;
const CAPTURE_SYNC_INTERVAL_MS = 2000;

const presetBackgrounds = {
  aurora: "linear-gradient(135deg, #f8efe1 0%, #f6fbff 44%, #ecf0ff 100%)",
  night: "linear-gradient(135deg, #101827 0%, #213d5a 54%, #0f172a 100%)",
  mint: "linear-gradient(135deg, #e8fff4 0%, #d6e8ff 55%, #f7fff8 100%)",
  sunset: "linear-gradient(135deg, #ffe6e0 0%, #fff7c2 45%, #dff4ff 100%)",
};

const backgroundStyle = computed(() => {
  const glassBlur = `${Math.round((Number(store.background.blur) || 0) * 0.45)}px`;
  const sharedStyle = {
    "--glass-blur": glassBlur,
    "--drawer-blur": glassBlur,
  };
  const overlay = `linear-gradient(rgba(247,250,255,${store.background.opacity}), rgba(247,250,255,${store.background.opacity}))`;
  if (store.background.mode === "image" && store.background.image_path) {
    return {
      ...sharedStyle,
      backgroundImage: `${overlay}, url("${store.background.image_path}")`,
    };
  }
  if (store.background.mode === "color" && store.background.color) {
    return { ...sharedStyle, background: store.background.color };
  }
  return { ...sharedStyle, background: presetBackgrounds[store.background.preset] || presetBackgrounds.aurora };
});

onMounted(async () => {
  await loadInitialData();
});

onBeforeUnmount(() => {
  if (pollTimer) window.clearInterval(pollTimer);
});

async function loadInitialData() {
  await safeRun(async () => {
    const background = await api.getSetting("background");
    Object.assign(store.background, background);
  });
}

async function startCapture() {
  await safeRun(async () => {
    store.loading = true;
    const batch = await api.startCapture(store.targetUrl.trim());
    store.targetUrl = batch.target_url;
    store.currentBatch = batch;
    store.requests = [];
    store.selectedRequest = null;
    store.selectedRequestIds.clear();
    store.viewedRequestIds.clear();
    store.notice = "浏览器已启动。请在打开的页面中操作，新增请求会自动标记 NEW。";
    await loadRequests(batch.batch_no);
    startPolling();
  });
}

function startPolling() {
  if (pollTimer) window.clearInterval(pollTimer);
  syncCurrentRequests();
  pollTimer = window.setInterval(syncCurrentRequests, CAPTURE_SYNC_INTERVAL_MS);
}

async function syncCurrentRequests() {
  if (!store.currentBatch || syncing) return;
  syncing = true;
  try {
    await safeRun(async () => {
      const newRequests = await api.syncRequests(store.currentBatch.batch_no);
      mergeRequests(newRequests);
    }, false);
  } finally {
    syncing = false;
  }
}

function mergeRequests(newRequests) {
  if (!newRequests.length) return;
  const requestMap = new Map(store.requests.map((item) => [item.request_id, item]));
  for (const request of newRequests) {
    const existing = requestMap.get(request.request_id);
    const hasViewed = store.viewedRequestIds.has(request.id) || store.viewedRequestIds.has(existing?.id);
    requestMap.set(request.request_id, {
      ...(existing || {}),
      ...request,
      is_new: hasViewed ? false : Boolean(existing?.is_new || request.is_new),
    });
  }
  store.requests = Array.from(requestMap.values())
    .sort((left, right) => new Date(right.start_time) - new Date(left.start_time));
}

async function clearCurrent() {
  if (!store.currentBatch) {
    store.error = "当前没有采集批次可清空。";
    return;
  }
  await safeRun(async () => {
    await api.clearCurrent(store.currentBatch.batch_no);
    store.requests = [];
    store.selectedRequest = null;
    store.selectedRequestIds.clear();
    store.notice = "当前采集已清空，历史采集记录不会被删除。";
  });
}

async function resetBrowserProfile() {
  await safeRun(async () => {
    if (pollTimer) window.clearInterval(pollTimer);
    pollTimer = null;
    await api.resetBrowserProfile();
    store.currentBatch = null;
    store.requests = [];
    store.selectedRequest = null;
    store.selectedRequestIds.clear();
    store.viewedRequestIds.clear();
    store.notice = "登录态已重置。请重新启动浏览器，并在目标网站完成登录后继续采集。";
  });
}

async function loadRequests(batchNo = store.currentBatch?.batch_no) {
  if (!batchNo) return;
  const requests = await api.listRequests({
    batch_no: batchNo,
    method: "ALL",
    keyword: "",
    only_api: false,
    limit: 1000,
  });
  store.requests = requests.map((request) => ({
    ...request,
    is_new: store.viewedRequestIds.has(request.id) ? false : request.is_new,
  }));
}

async function selectRequest(id) {
  store.viewedRequestIds.add(id);
  store.requests = store.requests.map((request) => (request.id === id ? { ...request, is_new: false } : request));
  const detail = await api.getRequestDetail(id);
  store.selectedRequest = { ...detail, is_new: false };
  // 响应体异步加载，不阻塞首屏展示
  if (detail.is_api) {
    api.getResponseBody(id).then((result) => {
      if (store.selectedRequest?.id === id && result.body !== undefined) {
        store.selectedRequest = { ...store.selectedRequest, response_body: result.body };
      }
    }).catch(() => {});
  }
}

async function quickBackground(preset) {
  await saveSettings({ ...store.background, mode: "preset", preset, image_path: "" });
}

async function saveSettings(value) {
  await safeRun(async () => {
    const bgPayload = (({ mode, preset, color, image_path, blur, opacity }) =>
      ({ mode, preset, color, image_path, blur, opacity }))(value);
    const savedBg = await api.saveSetting({ key: "background", value: bgPayload, description: "用户界面背景设置" });
    Object.assign(store.background, savedBg);
    settingsOpen.value = false;
    store.notice = "设置已保存。";
  });
}

async function safeRun(task, showLoading = true) {
  try {
    store.error = "";
    if (showLoading) store.loading = true;
    await task();
  } catch (error) {
    store.error = error.message || "操作失败，请稍后重试。";
  } finally {
    store.loading = false;
    if (store.notice) window.setTimeout(() => (store.notice = ""), 2600);
    if (store.error) window.setTimeout(() => (store.error = ""), 4200);
  }
}
</script>
