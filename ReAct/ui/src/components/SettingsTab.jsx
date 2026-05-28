import React, { useEffect, useState } from 'react';
import { api } from '../api.js';

const GEMINI_MODELS = [
  'gemini-2.0-flash',
  'gemini-2.0-flash-lite',
  'gemini-1.5-flash',
  'gemini-1.5-pro',
];

export default function SettingsTab({ onSaved }) {
  const [config, setConfig] = useState(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [savedAt, setSavedAt] = useState(null);

  useEffect(() => {
    api.getConfig().then(setConfig).catch((e) => setError(e.message));
  }, []);

  if (!config) {
    return <div className="hint">Loading settings…</div>;
  }

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      await api.updateConfig({
        mcp_server_url: config.mcp_server_url,
        gemini_model: config.gemini_model,
        max_rounds: Number(config.max_rounds) || 8,
      });
      setSavedAt(new Date().toLocaleTimeString());
      onSaved?.();
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="settings">
      <h3>Runtime configuration</h3>
      <p className="hint">
        Changes apply immediately for this server process. Persistent settings
        (API keys, GitHub token, default ports) live in <code>ReAct/.env</code>.
      </p>

      <label className="field">
        <span>MCP server URL</span>
        <input
          value={config.mcp_server_url || ''}
          onChange={(e) => setConfig({ ...config, mcp_server_url: e.target.value })}
          placeholder="http://localhost:8000"
        />
      </label>

      <label className="field">
        <span>Gemini model</span>
        <select
          value={config.gemini_model || ''}
          onChange={(e) => setConfig({ ...config, gemini_model: e.target.value })}
        >
          {GEMINI_MODELS.map((m) => (
            <option key={m} value={m}>{m}</option>
          ))}
        </select>
      </label>

      <label className="field">
        <span>Max ReAct rounds</span>
        <input
          type="number"
          min={1}
          max={20}
          value={config.max_rounds || 8}
          onChange={(e) => setConfig({ ...config, max_rounds: e.target.value })}
        />
      </label>

      <div className="field">
        <span>Tool allowlist ({config.tool_allowlist?.length || 0})</span>
        <div className="chips">
          {(config.tool_allowlist || []).map((t) => (
            <span key={t} className="chip mono">{t}</span>
          ))}
        </div>
        <small className="hint">Toggle individual tools on the MCP Tools tab.</small>
      </div>

      {error && <div className="error">{error}</div>}

      <div className="actions">
        <button className="primary-btn" onClick={save} disabled={saving}>
          {saving ? 'Saving…' : 'Save'}
        </button>
        {savedAt && <span className="hint">Saved at {savedAt}</span>}
      </div>

      <details className="env-help">
        <summary>Environment variables (set in <code>ReAct/.env</code>)</summary>
        <ul>
          <li><code>GEMINI_API_KEY</code> — free key from Google AI Studio</li>
          <li><code>GITHUB_TOKEN</code> — for listing repos & PRs</li>
          <li><code>MCP_SERVER_URL</code> — default <code>http://localhost:8000</code></li>
          <li><code>REACT_BACKEND_PORT</code> — default <code>8090</code></li>
        </ul>
      </details>
    </div>
  );
}
