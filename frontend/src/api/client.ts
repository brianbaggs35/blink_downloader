/** Thin typed wrapper around fetch for the same-origin /api surface. */

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

interface RequestOptions {
  method?: string;
  json?: unknown;
  form?: Record<string, string>;
  /** Statuses (besides 2xx) whose body should be returned instead of thrown. */
  allow?: number[];
}

interface ValidationItem {
  msg?: string;
}

function extractDetail(body: unknown, fallback: string): string {
  if (typeof body === "object" && body !== null && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") {
      return detail;
    }
    if (Array.isArray(detail) && detail.length > 0) {
      const first = detail[0] as ValidationItem;
      if (typeof first.msg === "string") {
        return first.msg;
      }
    }
  }
  return fallback;
}

export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const init: RequestInit = {
    method: options.method ?? (options.json !== undefined || options.form ? "POST" : "GET"),
  };
  if (options.json !== undefined) {
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(options.json);
  } else if (options.form) {
    init.body = new URLSearchParams(options.form);
  }

  const response = await fetch(`/api${path}`, init);

  if (!response.ok && !options.allow?.includes(response.status)) {
    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      body = null;
    }
    throw new ApiError(response.status, extractDetail(body, response.statusText));
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}
