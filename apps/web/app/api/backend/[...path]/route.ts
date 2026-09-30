import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

function backendBase() {
  const raw = process.env.API_INTERNAL_URL || process.env.NEXT_PUBLIC_API_URL;
  if (!raw) throw new Error("API_INTERNAL_URL is not configured");
  return raw.replace(/\/$/, "");
}

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const search = request.nextUrl.search || "";
  const url = `${backendBase()}/${path.join("/")}${search}`;

  const headers = new Headers();
  for (const [key, value] of request.headers.entries()) {
    const lower = key.toLowerCase();
    if (["host", "content-length", "connection", "accept-encoding"].includes(lower)) continue;
    headers.set(key, value);
  }

  let body: ArrayBuffer | undefined;
  if (!["GET", "HEAD"].includes(request.method)) {
    body = await request.arrayBuffer();
  }

  try {
    const response = await fetch(url, {
      method: request.method,
      headers,
      body,
      cache: "no-store",
      redirect: "manual",
    });

    const responseHeaders = new Headers();
    const contentType = response.headers.get("content-type");
    if (contentType) responseHeaders.set("content-type", contentType);
    const location = response.headers.get("location");
    if (location) responseHeaders.set("location", location);
    responseHeaders.set("cache-control", "no-store");

    return new NextResponse(await response.arrayBuffer(), {
      status: response.status,
      headers: responseHeaders,
    });
  } catch {
    return NextResponse.json(
      { detail: "PRIMEVPN backend is temporarily unreachable" },
      { status: 502 },
    );
  }
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
