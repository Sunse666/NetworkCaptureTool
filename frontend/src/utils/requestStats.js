export function getLatestRequestsByPath(requests) {
  // 同一路径同一方法只保留最新请求，保证列表展示和左侧统计口径一致。
  const latestByPath = new Map();
  for (const request of requests) {
    const key = `${request.method}:${request.path}`;
    const existing = latestByPath.get(key);
    if (!existing || new Date(request.start_time).getTime() >= new Date(existing.start_time).getTime()) {
      latestByPath.set(key, request);
    }
  }
  return Array.from(latestByPath.values()).sort((left, right) => new Date(right.start_time) - new Date(left.start_time));
}
