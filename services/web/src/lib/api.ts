/** 统一 API 响应结构（硬约束 8：接口统一 {code, message, data}） */
export interface ApiResponse<T> {
  code: 0 | 1;
  message: string;
  data: T;
}

export async function apiGet<T>(url: string): Promise<ApiResponse<T>> {
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) {
    return { code: 1, message: `HTTP ${res.status}`, data: null as T };
  }
  return res.json();
}

export async function apiPost<T>(url: string, body?: unknown): Promise<ApiResponse<T>> {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    return { code: 1, message: `HTTP ${res.status}`, data: null as T };
  }
  return res.json();
}

export async function apiDelete<T>(url: string, body?: unknown): Promise<ApiResponse<T>> {
  const res = await fetch(url, {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    return { code: 1, message: `HTTP ${res.status}`, data: null as T };
  }
  return res.json();
}
