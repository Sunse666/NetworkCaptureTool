<template>
  <div v-if="open && store.selectedRequest" class="detail-modal-mask" @click.self="$emit('close')">
    <section class="panel detail detail-modal">
      <div class="detail-title">
        <div>
          <h2>{{ store.selectedRequest.path }}</h2>
          <p>{{ store.selectedRequest.domain }} · {{ store.selectedRequest.method }} · {{ store.selectedRequest.status_code || "-" }} · {{ store.selectedRequest.duration_ms || "-" }}ms</p>
        </div>
        <div class="detail-actions">
          <button class="copy" :class="{ copied }" @click="copyCurl">
            {{ copied ? "已复制" : "复制 cURL" }}
          </button>
          <button class="modal-close" @click="$emit('close')">关闭</button>
        </div>
      </div>

      <div class="tabs">
        <button v-for="tab in tabs" :key="tab.key" class="tab" :class="{ active: activeTab === tab.key }" @click="activeTab = tab.key">
          {{ tab.label }}
        </button>
      </div>

      <div v-if="activeTab === 'params'" class="param-grid">
        <ParamCard title="Query 参数" :data="store.selectedRequest.query_params" :marks="store.selectedRequest.dynamic_marks" />
        <ParamCard title="Body 参数" :data="store.selectedRequest.request_body" :marks="store.selectedRequest.dynamic_marks" copyable />
      </div>

      <div v-else-if="activeTab === 'headers'" class="param-grid">
        <ParamCard title="Request Headers" :data="store.selectedRequest.request_headers" />
        <ParamCard title="Response Headers" :data="store.selectedRequest.response_headers" />
      </div>

      <div v-else-if="activeTab === 'cookies'" class="param-grid one-col">
        <ParamCard title="Cookie" :data="store.selectedRequest.cookies" />
      </div>

      <div v-else-if="activeTab === 'tokens'" class="param-grid one-col">
        <ParamCard title="令牌信息" :data="tokenData" copyable copy-label="复制令牌 JSON" />
      </div>

      <div v-else-if="activeTab === 'response'" class="response-view">
        <div v-if="hiddenResponse" class="payload-placeholder response-placeholder">
          <div class="payload-icon">RES</div>
          <strong>响应内容已隐藏</strong>
          <p>{{ hiddenResponse.reason }}</p>
          <small>大小约 {{ hiddenResponse.size || 0 }} 字符。可在 cURL 或接口工具中进一步调试。</small>
        </div>
        <pre v-else class="code-block">{{ jsonPreview(store.selectedRequest.response_body) }}</pre>
      </div>
      <pre v-else class="curl">{{ store.selectedRequest.clean_curl || "暂无 cURL" }}</pre>
    </section>
  </div>
</template>

<script setup>
import { computed, ref } from "vue";
import ParamCard from "./ParamCard.vue";
import { captureStore as store } from "../stores/captureStore";
import { jsonPreview } from "../utils/format";

defineProps({ open: Boolean });
defineEmits(["close"]);

const activeTab = ref("params");
const copied = ref(false);
const hiddenResponse = computed(() => {
  const body = store.selectedRequest?.response_body;
  return body && typeof body === "object" && body.__hidden_payload__ ? body : null;
});
const tabs = [
  { key: "params", label: "参数视图" },
  { key: "headers", label: "Headers" },
  { key: "cookies", label: "Cookie" },
  { key: "tokens", label: "令牌" },
  { key: "response", label: "响应" },
  { key: "curl", label: "cURL" },
];
const tokenData = computed(() => {
  // 令牌页签集中展示鉴权相关字段，方便直接复制到接口工具调试。
  const tokens = store.selectedRequest?.auth_tokens || [];
  return Object.fromEntries(tokens.map((item) => [`${item.source}.${item.name}`, item.value]));
});

async function copyCurl() {
  // 复制后使用全局提示反馈，避免用户不知道操作是否成功。
  const text = store.selectedRequest?.clean_curl || "";
  if (!text) return;
  await navigator.clipboard.writeText(text);
  copied.value = true;
  store.notice = "精简 cURL 已复制，可以粘贴到 Postman 或接口自动化脚本中。";
  window.setTimeout(() => {
    copied.value = false;
  }, 1200);
}

</script>
