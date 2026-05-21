import { reactive } from "vue";

// 轻量状态容器：首期不引入额外状态管理库，降低耦合和依赖复杂度。
export const captureStore = reactive({
  // 目标地址由用户输入，避免开发/测试时残留的网址被当作默认目标自动打开。
  targetUrl: "",
  currentBatch: null,
  requests: [],
  selectedRequest: null,
  selectedRequestIds: new Set(),
  viewedRequestIds: new Set(),
  loading: false,
  keyword: "",
  method: "ALL",
  onlyApi: true,
  notice: "",
  error: "",
  background: {
    mode: "preset",
    preset: "aurora",
    image_path: "",
    color: "",
    blur: 18,
    opacity: 0.52,
  },
});
