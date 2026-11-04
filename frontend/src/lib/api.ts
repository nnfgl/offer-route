export type User = { id: string; email: string; display_name: string };
export type Session = { user: User; csrf_token: string };
export type Workspace = {
  user: User;
  modules: { id: string; title: string; status: 'planned' | 'available' }[];
};

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 20000);
  try {
    const response = await fetch(`/api/v1${path}`, {
      ...options, credentials: 'include', signal: controller.signal,
      headers: { 'Content-Type': 'application/json', ...options.headers },
    });
    if (!response.ok) {
      const body = await response.json().catch(() => null);
      throw new ApiError(response.status, body?.error?.message ?? '服务暂时不可用，请稍后重试');
    }
    return response.status === 204 ? undefined as T : await response.json() as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new Error('连接失败或请求超时，请检查网络后重试');
  } finally { window.clearTimeout(timeout); }
}
