// Backend client. Uses fetch rather than adding axios: the backend speaks
// plain JSON and one multipart upload, which fetch covers natively.

export const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

/**
 * The backend returns `detail` in two shapes: a plain string from its own
 * DataError/AuditInputError handlers, and FastAPI's array of field errors when
 * a request fails schema validation. Both must end up as one readable line,
 * because a raw "[object Object]" in an alert banner tells nobody anything.
 */
function readDetail(body, status) {
  const detail = body?.detail;
  if (typeof detail === "string") return detail;

  if (Array.isArray(detail)) {
    return detail
      .map((e) => {
        const field = (e.loc ?? []).filter((p) => p !== "body" && p !== "query").join(".");
        const msg = String(e.msg ?? "invalid value").replace(/^Value error, /, "");
        return field ? `${field}: ${msg}` : msg;
      })
      .join("; ");
  }
  return `Request failed with status ${status}.`;
}

async function request(path, init) {
  let response;
  try {
    response = await fetch(`${API_BASE}${path}`, init);
  } catch (err) {
    // An abort is a deliberate supersede, not a failure. Rewriting it as a
    // connection error would defeat the caller's `err.name === "AbortError"`
    // guard and show a false "backend is down" banner over a live request.
    if (err.name === "AbortError") throw err;
    // Otherwise fetch only rejects on a transport failure, which here almost
    // always means the backend is not running.
    throw new Error(
      `Cannot reach the audit engine at ${API_BASE}. Start it with "uvicorn app.main:app --port 8000".`,
    );
  }

  const body = await response.json().catch(() => null);
  if (!response.ok) throw new Error(readDetail(body, response.status));
  // A 2xx whose body will not parse is still a failure. Returning null here
  // would render the "no audit yet" empty state with no error at all, which
  // is undiagnosable for whoever is looking at it.
  if (body === null) {
    throw new Error(`The engine returned status ${response.status} with no readable JSON body.`);
  }
  return body;
}

export function checkHealth(signal) {
  return request("/health", { signal });
}

export function runAudit(payload, signal) {
  return request("/api/v1/audit/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal,
  });
}

export function uploadAudit(file, signal) {
  const form = new FormData();
  form.append("file", file);
  // No Content-Type header: the browser must set the multipart boundary.
  return request("/api/v1/audit/upload", { method: "POST", body: form, signal });
}
