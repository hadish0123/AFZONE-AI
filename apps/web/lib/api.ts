const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type SessionUser = {
  id: string;
  username: string;
  display_name?: string | null;
  role: "owner" | "admin";
  wallet_balance_toman?: string;
};

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

  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers,
    cache: "no-store",
  });

  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {}
    throw new Error(detail);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export async function login(username: string, password: string) {
  return api<{
    access_token: string;
    token_type: string;
    user: SessionUser;
  }>("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}
