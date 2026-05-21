<template>
  <header class="topbar">
    <div class="brand">
      <div class="logo">∿</div>
      <div>
        <strong>接口捕获</strong>
        <small>Browser Network Studio</small>
      </div>
    </div>

    <label class="url-box">
      <span>目标地址</span>
      <input v-model="store.targetUrl" placeholder="请输入目标网站地址，例如 https://example.com" />
    </label>

    <div class="actions">
      <button class="btn" @click="$emit('clear-current')">一键清除当前采集</button>
      <button class="btn" :disabled="store.loading" title="清除内置浏览器保存的登录态和过期 token" @click="$emit('reset-profile')">重置登录态</button>
      <button class="btn icon" title="设置" @click="$emit('open-settings')">⚙</button>
      <button class="btn primary" :disabled="store.loading" @click="$emit('start')">
        {{ store.loading ? "启动中..." : "启动浏览器" }}
      </button>
    </div>
  </header>
</template>

<script setup>
import { captureStore as store } from "../stores/captureStore";

// 顶栏只负责触发用户操作，真正的业务请求由 App 统一协调，降低组件耦合。
defineEmits(["start", "clear-current", "reset-profile", "open-settings"]);
</script>
