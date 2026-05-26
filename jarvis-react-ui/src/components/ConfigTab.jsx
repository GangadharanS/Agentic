import { useState, useEffect } from 'react';
import api from '../services/api';

function ConfigTab({ showToast, isConnected }) {
  const [servers, setServers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [newServer, setNewServer] = useState({ name: '', url: '' });

  useEffect(() => {
    loadServers();
  }, []);

  const loadServers = async () => {
    setLoading(true);
    try {
      const result = await api.getMcpServers();
      setServers(result.servers || []);
    } catch (error) {
      console.error('Failed to load MCP servers:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleAddServer = () => {
    if (!newServer.name.trim() || !newServer.url.trim()) {
      showToast('Please fill in server name and URL', 'warning');
      return;
    }
    setServers(prev => [...prev, { ...newServer, status: 'disconnected' }]);
    setNewServer({ name: '', url: '' });
    showToast('Server added (restart required to connect)', 'info');
  };

  const handleRemoveServer = (index) => {
    setServers(prev => prev.filter((_, i) => i !== index));
    showToast('Server removed', 'success');
  };

  return (
    <div className="tab-content active">
      <div className="config-section">
        <h2>⚙️ Configuration</h2>
        <p className="config-description">
          Manage MCP server connections and application settings.
        </p>

        <div className="server-list">
          <h3>MCP Servers</h3>
          
          {loading ? (
            <div className="loading">
              <div className="loading-spinner"></div>
              <span>Loading servers...</span>
            </div>
          ) : (
            <>
              <div className="server-card main-server">
                <div className={`server-status ${isConnected ? 'connected' : 'disconnected'}`}></div>
                <div className="server-info">
                  <div className="server-name">Primary MCP Server</div>
                  <div className="server-url">http://localhost:8000</div>
                  <div className="server-desc">Main server for PR reviews, JIRA, and GitHub integration</div>
                </div>
                <div className="server-actions">
                  <button className="server-btn" onClick={loadServers}>
                    🔄 Refresh
                  </button>
                </div>
              </div>

              {servers.map((server, index) => (
                <div key={index} className="server-card">
                  <div className={`server-status ${server.status === 'connected' ? 'connected' : 'disconnected'}`}></div>
                  <div className="server-info">
                    <div className="server-name">{server.name}</div>
                    <div className="server-url">{server.url}</div>
                    {server.description && (
                      <div className="server-desc">{server.description}</div>
                    )}
                    {server.tools && server.tools.length > 0 && (
                      <div className="server-tools">
                        <span className="tools-label">Tools:</span>
                        <div className="tools-list">
                          {server.tools.slice(0, 5).map((tool, i) => (
                            <span key={i} className="tool-tag">{tool}</span>
                          ))}
                          {server.tools.length > 5 && (
                            <span className="tool-tag more">+{server.tools.length - 5} more</span>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                  <div className="server-actions">
                    <button 
                      className="server-btn delete"
                      onClick={() => handleRemoveServer(index)}
                    >
                      🗑️ Remove
                    </button>
                  </div>
                </div>
              ))}
            </>
          )}
        </div>

        <div className="add-server-form">
          <h3>Add New MCP Server</h3>
          <div className="form-row">
            <div className="form-group">
              <label>Server Name</label>
              <input
                type="text"
                placeholder="My MCP Server"
                value={newServer.name}
                onChange={(e) => setNewServer(prev => ({ ...prev, name: e.target.value }))}
              />
            </div>
            <div className="form-group">
              <label>Server URL</label>
              <input
                type="text"
                placeholder="http://localhost:8001"
                value={newServer.url}
                onChange={(e) => setNewServer(prev => ({ ...prev, url: e.target.value }))}
              />
            </div>
          </div>
          <button className="add-server-btn" onClick={handleAddServer}>
            ➕ Add Server
          </button>
        </div>

        <div className="config-info">
          <h3>Environment Variables</h3>
          <p>Configure these in your <code>.env</code> file:</p>
          <ul className="env-list">
            <li><code>GEMINI_API_KEY</code> - Google Gemini API key for AI processing</li>
            <li><code>GITHUB_TOKEN</code> - GitHub personal access token</li>
            <li><code>JIRA_API_TOKEN</code> - JIRA API token for issue integration</li>
            <li><code>BITBUCKET_API_TOKEN</code> - Bitbucket API token</li>
          </ul>
        </div>
      </div>
    </div>
  );
}

export default ConfigTab;
