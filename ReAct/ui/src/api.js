// In dev, Vite proxies /api → http://localhost:8090 (see vite.config.js).
// In prod, set VITE_API_BASE to your deployed backend URL (e.g. https://react-pr-api.azurewebsites.net).
// Leave it unset when SWA `routes` proxy /api/* to the backend for you.
const BASE = (import.meta.env.VITE_API_BASE || '') + '/api';

async function jsonOrThrow(response) {
  const text = await response.text();
  let data;
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    throw new Error(text || `HTTP ${response.status}`);
  }
  if (!response.ok) {
    throw new Error(data.detail || data.message || `HTTP ${response.status}`);
  }
  return data;
}

export const api = {
  health: () => fetch(`${BASE}/health`).then(jsonOrThrow),

  listRepos: () => fetch(`${BASE}/repos`).then(jsonOrThrow),

  listPRs: (owner, repo, state = 'open') =>
    fetch(`${BASE}/repos/${owner}/${repo}/prs?state=${state}`).then(jsonOrThrow),

  prSummary: (owner, repo, prId) =>
    fetch(`${BASE}/repos/${owner}/${repo}/prs/${prId}`).then(jsonOrThrow),

  listTools: () => fetch(`${BASE}/mcp/tools`).then(jsonOrThrow),

  getConfig: () => fetch(`${BASE}/mcp/config`).then(jsonOrThrow),

  updateConfig: (body) =>
    fetch(`${BASE}/mcp/config`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(jsonOrThrow),

  testTool: (name, args) =>
    fetch(`${BASE}/mcp/tools/${encodeURIComponent(name)}/test`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ arguments: args }),
    }).then(jsonOrThrow),

  review: (body) =>
    fetch(`${BASE}/review`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(jsonOrThrow),

  /**
   * Streams ReAct events via fetch (manual SSE parsing).
   * onEvent receives { type, data } objects.
   */
  reviewStream: async (body, onEvent, signal) => {
    const response = await fetch(`${BASE}/review/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal,
    });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const messages = buffer.split('\n\n');
      buffer = messages.pop() || '';
      for (const message of messages) {
        if (!message.trim()) continue;
        const lines = message.split('\n');
        let event = 'message';
        let dataText = '';
        for (const line of lines) {
          if (line.startsWith('event:')) event = line.slice(6).trim();
          else if (line.startsWith('data:')) dataText += line.slice(5).trim();
        }
        if (!dataText) continue;
        try {
          onEvent({ type: event, data: JSON.parse(dataText) });
        } catch {
          onEvent({ type: event, data: dataText });
        }
      }
    }
  },
};
