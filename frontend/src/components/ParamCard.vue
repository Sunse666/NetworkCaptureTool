<template>
  <article class="param-card" :class="{ 'is-hidden-payload': hiddenPayload }">
    <div class="param-card-head">
      <h3>{{ title }}</h3>
      <button v-if="copyable && copyText" class="copy-json" :class="{ copied }" @click="copyJson">
        {{ copied ? "已复制" : copyLabel }}
      </button>
    </div>
    <div v-if="hiddenPayload" class="payload-placeholder">
      <div class="payload-icon">BIN</div>
      <strong>已隐藏非文本内容</strong>
      <p>{{ hiddenReason }}</p>
      <small>可切换到 cURL 标签复制原始请求，避免参数视图出现乱码。</small>
    </div>
    <template v-else-if="rows.length">
      <div v-for="row in rows" :key="row.key" class="kv">
        <span class="key">{{ row.key }}</span>
        <span class="value" :title="row.value">{{ row.value }}</span>
        <span v-if="markMap[row.key]" class="pill">{{ markMap[row.key] }}</span>
        <button class="copy-row" :class="{ copied: copiedKey === row.key }" @click="copyValue(row)">
          {{ copiedKey === row.key ? "已复制" : "复制" }}
        </button>
      </div>
    </template>
    <pre v-else-if="rawText" class="mini-code">{{ rawText }}</pre>
    <p v-else class="muted-text">暂无数据</p>
  </article>
</template>

<script setup>
import { computed, ref } from "vue";
import { captureStore as store } from "../stores/captureStore";
import { isLikelyBinaryText, jsonPreview, parseFormText, toCopyableJson } from "../utils/format";

const props = defineProps({
  title: { type: String, required: true },
  data: { type: [Object, Array, String, Number, Boolean], default: null },
  marks: { type: Array, default: () => [] },
  copyable: { type: Boolean, default: false },
  copyLabel: { type: String, default: "复制 Body JSON" },
});

const copied = ref(false);
const copiedKey = ref("");

const markMap = computed(() => {
  // 动态参数标签按 key 映射，展示时保持参数和风险提示在同一行。
  const labels = {
    auth: "鉴权",
    signature: "签名",
    dynamic: "动态",
    pagination: "分页",
    business_id: "业务ID",
  };
  return Object.fromEntries(props.marks.map((item) => [item.key, labels[item.type] || "关注"]));
});

const normalizedData = computed(() => {
  // 字符串表单先解析为对象；疑似二进制内容保持原样，交给隐藏态处理。
  if (typeof props.data === "string") {
    return parseFormText(props.data) || props.data;
  }
  return props.data;
});

const hiddenPayload = computed(() => isLikelyBinaryText(props.data));

const hiddenReason = computed(() => {
  const length = typeof props.data === "string" ? props.data.length : 0;
  return `该内容疑似二进制、压缩体或 protobuf 数据，长度约 ${length} 字符，不适合直接渲染。`;
});

const rows = computed(() => {
  if (!normalizedData.value || typeof normalizedData.value !== "object" || Array.isArray(normalizedData.value)) return [];
  return Object.entries(normalizedData.value).map(([key, value]) => ({
    key,
    value: typeof value === "object" ? JSON.stringify(value) : String(value),
  }));
});

const rawText = computed(() => {
  if (!normalizedData.value || typeof normalizedData.value === "object" || hiddenPayload.value) return "";
  return jsonPreview(normalizedData.value);
});

const copyText = computed(() => {
  if (hiddenPayload.value) return "";
  return toCopyableJson(props.data);
});

async function copyJson() {
  // Body 参数单独复制为标准 JSON，方便直接粘贴到接口自动化脚本或 Postman。
  if (!copyText.value) return;
  try {
    await navigator.clipboard.writeText(copyText.value);
    copied.value = true;
    store.notice = `${props.title} 已按 JSON 格式复制，可单独粘贴使用。`;
    window.setTimeout(() => {
      copied.value = false;
    }, 1200);
  } catch {
    store.notice = "复制失败，请检查浏览器剪贴板权限。";
  }
}

async function copyValue(row) {
  // 长 Header、Cookie、Token 可单独复制，避免手动选择长文本时漏选。
  try {
    await navigator.clipboard.writeText(row.value);
    copiedKey.value = row.key;
    store.notice = `${row.key} 已复制完整值。`;
    window.setTimeout(() => {
      copiedKey.value = "";
    }, 1200);
  } catch {
    store.notice = "复制失败，请检查浏览器剪贴板权限。";
  }
}
</script>
