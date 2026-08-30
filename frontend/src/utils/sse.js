// SSE / streaming-fetch utilities.
//
// Supports two streaming response formats:
//
// 1. JSON event stream
//    data: {"type":"token","text":"hello"}\n
//    data: {"type":"done"}\n
//
// 2. Plain text stream
//    raw UTF-8 text chunks
//
// Uses fetch + ReadableStream instead of EventSource because we need:
// - POST requests
// - JSON request body
// - Django Session Cookie authentication
// - CSRF request header
// - AbortSignal support

import { LANG_KEY } from "../constants";

/**
 * Append ?lang= to the URL based on user preference.
 */
function withLang(url) {
  const lang =
    (typeof localStorage !== "undefined" && localStorage.getItem(LANG_KEY)) ||
    "zh";

  if (!lang) return url;

  const sep = url.includes("?") ? "&" : "?";

  return `${url}${sep}lang=${encodeURIComponent(lang)}`;
}

/**
 * Read Django CSRF token from the `csrftoken` cookie.
 */
function getCsrfFromCookie() {
  if (typeof document === "undefined") {
    return null;
  }

  const cookies = document.cookie.split(";");

  for (const cookie of cookies) {
    const [name, ...rest] = cookie.trim().split("=");

    if (name === "csrftoken") {
      const value = rest.join("=");

      try {
        return decodeURIComponent(value);
      } catch {
        return value;
      }
    }
  }

  return null;
}

/**
 * Merge caller headers with default JSON / Django CSRF headers.
 */
function createHeaders(inputHeaders) {
  const headers = new Headers(inputHeaders || {});

  if (!headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const csrf = getCsrfFromCookie();

  if (csrf && !headers.has("X-CSRFToken")) {
    headers.set("X-CSRFToken", csrf);
  }

  return headers;
}

/**
 * Low-level streaming request.
 *
 * Returns the raw Response.
 * The caller consumes response.body through one of the iterators below.
 */
export async function streamingFetch(url, init = {}) {
  const {
    headers: inputHeaders,
    method = "POST",
    credentials = "include",
    ...restInit
  } = init;

  const headers = createHeaders(inputHeaders);

  const response = await fetch(withLang(url), {
    ...restInit,
    method,
    credentials,
    headers,
  });

  if (!response.ok) {
    let message = `HTTP ${response.status}`;

    try {
      const text = await response.text();

      if (text.trim()) {
        message = text;
      } else if (response.statusText) {
        message = `${response.status} ${response.statusText}`;
      }
    } catch {
      if (response.statusText) {
        message = `${response.status} ${response.statusText}`;
      }
    }

    throw new Error(message);
  }

  if (!response.body) {
    throw new Error(
      "Response has no readable body. Streaming may not be supported in this environment.",
    );
  }

  return response;
}

/**
 * Parse one line from the project's SSE-style JSON protocol.
 *
 * Supported:
 *
 *   data: {"type":"token"}
 *   data:{"type":"token"}
 *
 * Ignored:
 *
 *   empty lines
 *   : heartbeat
 *   event:
 *   id:
 *   retry:
 */
function parseSSELine(line) {
  // Handle CRLF (\r\n).
  if (line.endsWith("\r")) {
    line = line.slice(0, -1);
  }

  if (!line) {
    return null;
  }

  // SSE heartbeat / comments.
  if (line.startsWith(":")) {
    return null;
  }

  // This project only consumes data fields.
  if (!line.startsWith("data:")) {
    return null;
  }

  let raw = line.slice(5);

  // SSE allows one optional space after ":".
  if (raw.startsWith(" ")) {
    raw = raw.slice(1);
  }

  raw = raw.trim();

  if (!raw) {
    return null;
  }

  return JSON.parse(raw);
}

/**
 * Iterate JSON events from the project's SSE-style response.
 *
 * Expected backend format:
 *
 *   data: {"type":"token","text":"你"}\n
 *   data: {"type":"token","text":"好"}\n
 *   data: {"type":"done"}\n
 *
 * HTTP chunks are not message boundaries, so an internal buffer
 * is required to reconstruct complete newline-delimited records.
 */
export async function* iterSSEEvents(response) {
  if (!response.body) {
    throw new Error("Response body is not readable");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");

  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();

      if (done) {
        break;
      }

      if (!value) {
        continue;
      }

      buffer += decoder.decode(value, {
        stream: true,
      });

      let newlineIndex;

      while ((newlineIndex = buffer.indexOf("\n")) !== -1) {
        const line = buffer.slice(0, newlineIndex);

        buffer = buffer.slice(newlineIndex + 1);

        try {
          const event = parseSSELine(line);

          if (event !== null) {
            yield event;
          }
        } catch (error) {
          if (error instanceof SyntaxError) {
            // Keep compatibility with the previous implementation:
            // malformed JSON events are silently ignored.
            continue;
          }

          throw error;
        }
      }
    }

    // Flush any UTF-8 bytes still held internally by TextDecoder.
    buffer += decoder.decode();

    // Handle a final event without trailing newline.
    const tail = buffer.trim();

    if (tail) {
      try {
        const event = parseSSELine(tail);

        if (event !== null) {
          yield event;
        }
      } catch (error) {
        if (!(error instanceof SyntaxError)) {
          throw error;
        }

        // Ignore malformed/truncated trailing event.
      }
    }
  } finally {
    reader.releaseLock();
  }
}

/**
 * Iterate decoded text chunks from a plain text streaming response.
 *
 * Each yielded value is incremental, NOT cumulative.
 */
export async function* iterTextChunks(response) {
  if (!response.body) {
    throw new Error("Response body is not readable");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");

  try {
    while (true) {
      const { done, value } = await reader.read();

      if (done) {
        break;
      }

      if (!value) {
        continue;
      }

      const chunk = decoder.decode(value, {
        stream: true,
      });

      if (chunk) {
        yield chunk;
      }
    }

    // Flush any remaining UTF-8 bytes.
    const tail = decoder.decode();

    if (tail) {
      yield tail;
    }
  } finally {
    reader.releaseLock();
  }
}
