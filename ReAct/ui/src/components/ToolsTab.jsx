import React, { useEffect, useState } from 'react';
import { api } from '../api.js';

export default function ToolsTab() {
  const [tools, setTools] = useState([]);
  const [allowlist, setAllowlist] = useState([]);
  const [filter, setFilter] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [testState, setTestState] = useState({});

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.listTools();
      setTools(data.tools || []);
      setAllowlist(data.allowlist || []);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const toggleAllow = async (name) => {
    const next = allowlist.includes(name)
      ? allowlist.filter((n) => n !== name)
      : [...allowlist, name];
    setAllowlist(next);
    try {
      await api.updateConfig({ tool_allowlist: next });
    } catch (e) {
      setError(e.message);
    }
  };

  const runTest = async (tool) => {
    const argsText = testState[tool.name]?.input || '{}';
    let args;
    try {
      args = JSON.parse(argsText);
    } catch (e) {
      setTestState((s) => ({
        ...s,
        [tool.name]: { ...(s[tool.name] || {}), output: `Invalid JSON: ${e.message}` },
      }));
      return;
    }
    setTestState((s) => ({
      ...s,
      [tool.name]: { ...(s[tool.name] || {}), output: 'Calling…' },
    }));
    try {
      const result = await api.testTool(tool.name, args);
      setTestState((s) => ({
        ...s,
        [tool.name]: { ...(s[tool.name] || {}), output: JSON.stringify(result, null, 2) },
      }));
    } catch (e) {
      setTestState((s) => ({
        ...s,
        [tool.name]: { ...(s[tool.name] || {}), output: `Error: ${e.message}` },
      }));
    }
  };

  const filtered = tools.filter(
    (t) =>
      !filter ||
      t.name.toLowerCase().includes(filter.toLowerCase()) ||
      (t.description || '').toLowerCase().includes(filter.toLowerCase())
  );

  return (
    <div className="tools">
      <div className="tools-bar">
        <input
          className="search"
          placeholder={`Filter ${tools.length} tools…`}
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
        <button className="link-btn" onClick={load} disabled={loading}>
          {loading ? '…' : 'Refresh'}
        </button>
        <span className="hint inline">
          Allowlist controls which MCP tools the ReAct agent can call.
          <b> {allowlist.length}</b> of <b>{tools.length}</b> enabled.
        </span>
      </div>

      {error && <div className="error">{error}</div>}

      <ul className="tool-list">
        {filtered.map((tool) => {
          const enabled = allowlist.includes(tool.name);
          const state = testState[tool.name] || {};
          return (
            <li key={tool.name} className="tool-item">
              <div className="tool-head">
                <label className="checkbox">
                  <input
                    type="checkbox"
                    checked={enabled}
                    onChange={() => toggleAllow(tool.name)}
                  />
                  <span className="tool-name"><code>{tool.name}</code></span>
                </label>
              </div>
              {tool.description && <div className="tool-desc">{tool.description}</div>}
              <details className="tool-details">
                <summary>Schema & test</summary>
                <pre className="code-block small">
                  {JSON.stringify(tool.input_schema || {}, null, 2)}
                </pre>
                <div className="tool-test">
                  <textarea
                    rows={3}
                    placeholder='{"arg": "value"}'
                    value={state.input || ''}
                    onChange={(e) =>
                      setTestState((s) => ({
                        ...s,
                        [tool.name]: { ...(s[tool.name] || {}), input: e.target.value },
                      }))
                    }
                  />
                  <button className="secondary-btn" onClick={() => runTest(tool)}>
                    Test call
                  </button>
                  {state.output && <pre className="code-block small">{state.output}</pre>}
                </div>
              </details>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
