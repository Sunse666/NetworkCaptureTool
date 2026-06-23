import { reactive } from "vue";

export const captureStore = reactive({
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
