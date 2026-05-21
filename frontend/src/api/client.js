const API_BASE = import.meta.env.VITE_API_BASE || "";
const DEFAULT_TIMEOUT_MS = 15000;

async function request(path, options = {}) {
  // 统一封装请求，集中处理 JSON、错误提示和后端统一响应结构。
  const { timeoutMs = DEFAULT_TIMEOUT_MS, ...fetchOptions } = options;
  const controller = new AbortController();
  const timer = timeoutMs > 0 ? window.setTimeout(() => controller.abort(), timeoutMs) : null;
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      headers: {
        "Content-Type": "application/json",
        ...(fetchOptions.headers || {}),
      },
      ...fetchOptions,
      signal: fetchOptions.signal || controller.signal,
    });
    const result = await response.json().catch(() => ({
      success: false,
      message: "服务返回内容无法解析，请检查后端是否正常运行。",
    }));
    if (!response.ok || result.success === false) {
      // 后端异常会尽量给出中文 message，detail 仅作为排查补充，避免用户只看到笼统失败。
      const detail = result.data?.detail ? ` 详情：${String(result.data.detail).slice(0, 160)}` : "";
      throw new Error(`${result.message || "请求失败，请稍后重试。"}${detail}`);
    }
    return result.data;
  } catch (error) {
    if (error.name === "AbortError") {
      throw new Error("请求超时，已停止等待；如果浏览器窗口已关闭，请重新点击启动浏览器。");
    }
    throw error;
  } finally {
    if (timer) window.clearTimeout(timer);
  }
}

export const api = {
  health: () => request("/api/health"),
  startCapture: (url) => request("/api/capture/start", {
    method: "POST",
    timeoutMs: 30000,
    body: JSON.stringify({ url }),
  }),
  resetBrowserProfile: () => request("/api/capture/reset-profile", { method: "POST", timeoutMs: 30000 }),
  syncRequests: (batchNo) => request(`/api/capture/sync${batchNo ? `?batch_no=${batchNo}` : ""}`, { method: "POST" }),
  clearCurrent: (batchNo) => request("/api/capture/current", {
    method: "DELETE",
    body: JSON.stringify({ batch_no: batchNo }),
  }),
  listRequests: (params) => request(`/api/requests?${new URLSearchParams(params).toString()}`),
  getRequestDetail: (id) => request(`/api/requests/${id}`),
  exportRequests: (requestIds, format) => request("/api/requests/export", {
    method: "POST",
    body: JSON.stringify({ request_ids: requestIds, format }),
  }),
  getSetting: (key) => request(`/api/settings/${key}`),
  saveSetting: (payload) => request("/api/settings", {
    method: "PUT",
    body: JSON.stringify(payload),
  }),
};
