import { describe, expect, it, vi } from "vitest";

import { api, ApiError } from "@/api/client";
import { jsonResponse } from "./helpers";

function stubFetch(response: Response) {
  const mock = vi.fn().mockResolvedValue(response);
  vi.stubGlobal("fetch", mock);
  return mock;
}

describe("api client", () => {
  it("performs a plain GET and parses JSON", async () => {
    const mock = stubFetch(jsonResponse({ hello: "world" }));
    const result = await api<{ hello: string }>("/health");
    expect(result).toEqual({ hello: "world" });
    expect(mock).toHaveBeenCalledWith("/api/health", { method: "GET" });
  });

  it("POSTs JSON bodies with the right content type", async () => {
    const mock = stubFetch(jsonResponse({ ok: true }, 201));
    await api("/setup", { json: { email: "a@b.com" } });
    const init = mock.mock.calls[0]?.[1] as RequestInit;
    expect(init.method).toBe("POST");
    expect(init.headers).toEqual({ "Content-Type": "application/json" });
    expect(init.body).toBe(JSON.stringify({ email: "a@b.com" }));
  });

  it("POSTs form bodies as URL-encoded params", async () => {
    const mock = stubFetch(new Response(null, { status: 204 }));
    const result = await api("/auth/login", { form: { username: "a@b.com", password: "pw" } });
    expect(result).toBeUndefined();
    const init = mock.mock.calls[0]?.[1] as RequestInit;
    expect(init.body).toBeInstanceOf(URLSearchParams);
    expect(String(init.body)).toBe("username=a%40b.com&password=pw");
  });

  it("honors an explicit method", async () => {
    const mock = stubFetch(jsonResponse({}));
    await api("/users/me", { method: "PATCH", json: { display_name: "B" } });
    expect((mock.mock.calls[0]?.[1] as RequestInit).method).toBe("PATCH");
  });

  it("throws ApiError with a string detail", async () => {
    stubFetch(jsonResponse({ detail: "Setup has already been completed." }, 409));
    const error = await api("/setup", { json: {} }).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(409);
    expect((error as ApiError).message).toBe("Setup has already been completed.");
  });

  it("extracts the first message from validation-error details", async () => {
    stubFetch(jsonResponse({ detail: [{ msg: "value is not a valid email" }] }, 422));
    const error = await api("/setup", { json: {} }).catch((e: unknown) => e);
    expect((error as ApiError).message).toBe("value is not a valid email");
  });

  it("falls back to statusText for unusable details", async () => {
    stubFetch(
      new Response(JSON.stringify({ detail: [] }), { status: 422, statusText: "Unprocessable" }),
    );
    const error = await api("/x").catch((e: unknown) => e);
    expect((error as ApiError).message).toBe("Unprocessable");
  });

  it("falls back when the first validation item has no msg", async () => {
    stubFetch(
      new Response(JSON.stringify({ detail: [{ loc: ["body"] }] }), {
        status: 422,
        statusText: "Unprocessable",
      }),
    );
    const error = await api("/x").catch((e: unknown) => e);
    expect((error as ApiError).message).toBe("Unprocessable");
  });

  it("falls back to statusText when the error body is not JSON", async () => {
    stubFetch(new Response("<html>gateway error</html>", { status: 502, statusText: "Bad Gateway" }));
    const error = await api("/x").catch((e: unknown) => e);
    expect((error as ApiError).message).toBe("Bad Gateway");
  });

  it("falls back to statusText when the body has no detail", async () => {
    stubFetch(new Response(JSON.stringify({ nope: 1 }), { status: 500, statusText: "Server Error" }));
    const error = await api("/x").catch((e: unknown) => e);
    expect((error as ApiError).message).toBe("Server Error");
  });

  it("returns the body for allowed error statuses", async () => {
    stubFetch(jsonResponse({ status: "degraded" }, 503));
    const result = await api<{ status: string }>("/health", { allow: [503] });
    expect(result.status).toBe("degraded");
  });
});
