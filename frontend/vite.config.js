import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

// Vite 配置保持简洁，开发环境通过代理转发到 Python 后端，避免前端写死接口域名。
export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8710",
    },
  },
});
