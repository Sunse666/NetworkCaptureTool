<template>
  <aside class="panel side">
    <div class="stat-card">
      <p class="section-title light">实时采集</p>
      <h3>{{ store.currentBatch ? "已连接 · Chromium" : "等待启动浏览器" }}</h3>
      <div class="stat-grid">
        <div>
          <b class="stat-number">{{ animatedTotal }}</b>
          <span>请求总数</span>
        </div>
        <div>
          <b class="stat-number">{{ animatedApi }}</b>
          <span>接口请求</span>
        </div>
      </div>
      <small>当前批次：{{ store.currentBatch?.batch_no || "-" }}</small>
    </div>

    <section>
      <p class="section-title">请求方法</p>
      <button
        v-for="item in methodStats"
        :key="item.method"
        class="filter"
        :class="{ active: store.method === item.method }"
        @click="store.method = item.method"
      >
        {{ item.label }}
        <span class="badge" :class="item.className">{{ animatedMethodCounts[item.method] ?? item.count }}</span>
      </button>
    </section>

    <section>
      <p class="section-title">背景切换</p>
      <button class="upload-bg" @click="$emit('open-settings')">上传自定义背景图片</button>
      <div class="theme-row">
        <button class="swatch one" @click="$emit('quick-background', 'aurora')"></button>
        <button class="swatch two" @click="$emit('quick-background', 'night')"></button>
        <button class="swatch three" @click="$emit('quick-background', 'mint')"></button>
        <button class="swatch four" @click="$emit('quick-background', 'sunset')"></button>
      </div>
    </section>
  </aside>
</template>

<script setup>
import { computed, reactive, ref, watch } from "vue";
import { captureStore as store } from "../stores/captureStore";
import { getLatestRequestsByPath } from "../utils/requestStats";

defineEmits(["open-settings", "quick-background"]);

const scopedRequests = computed(() => {
  // “只看接口请求”是全局展示筛选，侧边栏统计也要和右侧列表保持同一口径。
  if (!store.onlyApi) return store.requests;
  return store.requests.filter((item) => item.is_api);
});
const countedRequests = computed(() => getLatestRequestsByPath(scopedRequests.value));
const requestCount = computed(() => countedRequests.value.length);
const apiCount = computed(() => countedRequests.value.filter((item) => item.is_api).length);
const animatedTotal = useAnimatedNumber(requestCount);
const animatedApi = useAnimatedNumber(apiCount);
const animatedMethodCounts = reactive({});
const methodAnimationFrames = {};
const methodAnimationTokens = {};

const methodStats = computed(() => {
  // 方法统计使用去重后的全量数据，避免筛选按钮反向污染 ALL 数量。
  const count = (method) => countedRequests.value.filter((item) => item.method === method).length;
  return [
    { method: "ALL", label: "ALL", count: countedRequests.value.length, className: "all" },
    { method: "GET", label: "GET", count: count("GET"), className: "get" },
    { method: "POST", label: "POST", count: count("POST"), className: "post" },
    { method: "PUT", label: "PUT / PATCH", count: count("PUT") + count("PATCH"), className: "put" },
    { method: "DELETE", label: "DELETE", count: count("DELETE"), className: "del" },
  ];
});

watch(
  () => methodStats.value.map((item) => [item.method, item.count]),
  (items) => {
    for (const [method, count] of items) {
      animateNumber(animatedMethodCounts[method] ?? 0, count, (value) => {
        animatedMethodCounts[method] = value;
      }, method);
    }
  },
  { immediate: true },
);

function useAnimatedNumber(source) {
  const value = ref(source.value || 0);
  let frameId = 0;
  watch(
    source,
    (next, previous) => {
      if (frameId) cancelAnimationFrame(frameId);
      animateNumber(previous || 0, next || 0, (current) => {
        value.value = current;
      }, null, (id) => {
        frameId = id;
      });
    },
    { immediate: true },
  );
  return value;
}

function animateNumber(from, to, setValue, key = null, setFrameId = null) {
  // 数字变化用轻量 requestAnimationFrame，避免引入额外动画库。
  if (key && methodAnimationFrames[key]) {
    cancelAnimationFrame(methodAnimationFrames[key]);
  }
  const token = Symbol("number-animation");
  if (key) methodAnimationTokens[key] = token;
  const start = performance.now();
  const duration = 420;
  const safeFrom = Math.max(0, Number(from) || 0);
  const safeTo = Math.max(0, Number(to) || 0);
  const diff = safeTo - safeFrom;
  if (!diff) {
    setValue(safeTo);
    return;
  }
  function tick(now) {
    if (key && methodAnimationTokens[key] !== token) return;
    const progress = Math.min((now - start) / duration, 1);
    const eased = 1 - Math.pow(1 - progress, 3);
    setValue(Math.max(0, Math.round(safeFrom + diff * eased)));
    if (progress < 1) {
      const nextFrame = requestAnimationFrame(tick);
      if (key) methodAnimationFrames[key] = nextFrame;
      if (setFrameId) setFrameId(nextFrame);
    } else {
      setValue(safeTo);
      if (key) methodAnimationFrames[key] = 0;
      if (setFrameId) setFrameId(0);
    }
  }
  const firstFrame = requestAnimationFrame(tick);
  if (key) methodAnimationFrames[key] = firstFrame;
  if (setFrameId) setFrameId(firstFrame);
}
</script>
