export function statusClass(statusCode) {
  // 状态码颜色按常见接口调试工具习惯区分成功、重定向和错误。
  if (!statusCode) return "status muted";
  if (statusCode >= 500) return "status danger";
  if (statusCode >= 400) return "status warn";
  if (statusCode >= 300) return "status orange";
  return "status ok";
}

export function jsonPreview(value) {
  // 参数详情优先以格式化 JSON 展示，字符串则原样展示。
  if (value === null || value === undefined || value === "") return "暂无数据";
  if (typeof value === "string") return value;
  return JSON.stringify(value, null, 2);
}

export function isLikelyBinaryText(value) {
  // 性能日志可能把 protobuf、压缩体或二进制体当字符串返回，直接展示会形成乱码。
  if (typeof value !== "string") return false;
  const text = value.trim();
  if (!text) return false;
  const controlChars = text.match(/[\x00-\x08\x0B\x0C\x0E-\x1F]/g) || [];
  const replacementChars = text.match(/\uFFFD/g) || [];
  const visibleSample = text.slice(0, 220);
  const hasReadableSeparator = /[=&{}[\]":,\s]/.test(visibleSample);
  const looksLikeLongBlob = text.length > 180 && !hasReadableSeparator;
  return controlChars.length > 0 || replacementChars.length > 0 || looksLikeLongBlob;
}

export function parseFormText(value) {
  // 表单格式请求体转为对象后展示，比原始 a=1&b=2 更容易阅读。
  if (typeof value !== "string" || !value.includes("=")) return null;
  const params = new URLSearchParams(value);
  const entries = Array.from(params.entries());
  if (!entries.length) return null;
  return Object.fromEntries(entries);
}

export function parseJsonText(value) {
  // 后端兜底返回 JSON 字符串时，前端复制前再解析一次，避免复制成带转义的字符串。
  if (typeof value !== "string") return null;
  const text = value.trim();
  if (!text || !["{", "["].includes(text[0])) return null;
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

export function toCopyableJson(value) {
  // 复制参数时统一输出标准 JSON：JSON 字符串和表单字符串都会先转成对象。
  if (value === null || value === undefined || value === "") return "";
  const normalizedValue = typeof value === "string" ? parseJsonText(value) || parseFormText(value) || value : value;
  return JSON.stringify(normalizedValue, null, 2);
}
