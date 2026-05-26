function Header({ isConnected, loading, onRefresh }) {
  return (
    <header>
      <div className="logo">
        <div className="logo-icon">🤖</div>
        <h1>Jarvis Agent</h1>
      </div>
      
      <div className="status" onClick={onRefresh} style={{ cursor: 'pointer' }}>
        <span className={`status-dot ${isConnected ? 'connected' : ''}`}></span>
        <span>
          {loading ? 'Connecting...' : isConnected ? 'MCP Connected' : 'MCP Disconnected'}
        </span>
      </div>
    </header>
  );
}

export default Header;
