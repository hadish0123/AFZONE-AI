const API_URL = "/api/backend";

export type SessionUser = {
  id: string;
  username: string;
  display_name?: string | null;
  role: "owner" | "admin";
  wallet_balance_toman?: string;
  two_factor_enabled?: boolean;
};

export class ApiError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

type Session = {
  accessToken: string;
  refreshToken: string;
  user?: SessionUser;
};

const ACCESS_KEY = "primevpn_access";
const REFRESH_KEY = "primevpn_refresh";
const USER_KEY = "primevpn_user";

export function saveSession(session: Session) {
  if (typeof window === "undefined") return;
  localStorage.setItem(ACCESS_KEY, session.accessToken);
  localStorage.setItem(REFRESH_KEY, session.refreshToken);
  if (session.user) localStorage.setItem(USER_KEY, JSON.stringify(session.user));
}

export function clearSession() {
  if (typeof window === "undefined") return;
  localStorage.removeItem(ACCESS_KEY);
  localStorage.removeItem(REFRESH_KEY);
  localStorage.removeItem(USER_KEY);
}

export function storedSession(): Session | null {
  if (typeof window === "undefined") return null;
  const accessToken = localStorage.getItem(ACCESS_KEY);
  const refreshToken = localStorage.getItem(REFRESH_KEY);
  if (!accessToken || !refreshToken) return null;
  let user: SessionUser | undefined;
  try {
    user = JSON.parse(localStorage.getItem(USER_KEY) || "null") || undefined;
  } catch {}
  return { accessToken, refreshToken, user };
}

export async function api<T>(
  path: string,
  options: RequestInit = {},
  token?: string | null,
): Promise<T> {
  const headers = new Headers(options.headers);
  if (!headers.has("Content-Type") && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  if (token) headers.set("Authorization", `Bearer ${token}`);

  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...options,
      headers,
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, "ارتباط با سرور برقرار نشد");
  }

  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {}
    throw new ApiError(response.status, detail);
  }
  if (response.status === 204) return undefined as T;
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) return response.json() as Promise<T>;
  return (await response.text()) as T;
}

export async function login(username: string, password: string, otp?: string) {
  const result = await api<{
    access_token: string;
    refresh_token: string;
    token_type: string;
    expires_in: number;
    user: SessionUser;
  }>("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password, otp: otp || null }),
  });
  saveSession({
    accessToken: result.access_token,
    refreshToken: result.refresh_token,
    user: result.user,
  });
  return result;
}

export async function refreshSession(): Promise<string> {
  const session = storedSession();
  if (!session) throw new ApiError(401, "session_expired");
  const result = await api<{
    access_token: string;
    refresh_token: string;
  }>("/api/v1/auth/refresh", {
    method: "POST",
    body: JSON.stringify({ refresh_token: session.refreshToken }),
  });
  saveSession({
    accessToken: result.access_token,
    refreshToken: result.refresh_token,
    user: session.user,
  });
  return result.access_token;
}

export async function authApi<T>(path: string, options: RequestInit = {}): Promise<T> {
  const session = storedSession();
  if (!session) throw new ApiError(401, "session_expired");
  try {
    return await api<T>(path, options, session.accessToken);
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 401) throw error;
    try {
      const access = await refreshSession();
      return await api<T>(path, options, access);
    } catch (refreshError) {
      clearSession();
      throw refreshError;
    }
  }
}

export async function logout() {
  const session = storedSession();
  if (session) {
    try {
      await api("/api/v1/auth/logout", {
        method: "POST",
        body: JSON.stringify({ refresh_token: session.refreshToken }),
      });
    } catch {}
  }
  clearSession();
}
