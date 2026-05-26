import { useState, useRef, useEffect } from 'react';
import api from '../services/api';

function ChatTab({ tools, showToast }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!input.trim() || isLoading) return;

    const userMessage = input.trim();
    setInput('');
    setMessages(prev => [...prev, { role: 'user', content: userMessage }]);
    setIsLoading(true);

    try {
      const response = await api.chat(userMessage);
      setMessages(prev => [...prev, { 
        role: 'assistant', 
        content: response.response || response.message || 'No response received'
      }]);
    } catch (error) {
      showToast('Failed to get response: ' + error.message, 'error');
      setMessages(prev => [...prev, { 
        role: 'assistant', 
        content: 'Sorry, I encountered an error. Please try again.'
      }]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleToolClick = (tool) => {
    setInput(`Use the ${tool.name} tool to `);
  };

  return (
    <div className="tab-content active">
      <div className="assistant-section">
        <h2>🤖 AI Assistant</h2>
        <p className="assistant-description">
          Chat with Jarvis to review PRs, generate documentation, or ask questions about your codebase.
        </p>

        <div className="chat-container">
          <div className="chat-messages">
            {messages.length === 0 ? (
              <div className="chat-welcome">
                <div className="welcome-icon">🚀</div>
                <h3>Welcome to Jarvis Agent</h3>
                <p>I can help you with:</p>
                <ul className="capability-list">
                  <li>Review Pull Requests</li>
                  <li>Generate Documentation</li>
                  <li>Analyze Code Architecture</li>
                  <li>Answer Questions about APIs</li>
                </ul>
              </div>
            ) : (
              messages.map((msg, index) => (
                <div key={index} className={`chat-message ${msg.role}`}>
                  <div className="message-avatar">
                    {msg.role === 'user' ? '👤' : '🤖'}
                  </div>
                  <div className="message-content">
                    <div className="message-bubble">
                      {msg.content}
                    </div>
                  </div>
                </div>
              ))
            )}
            {isLoading && (
              <div className="chat-message assistant">
                <div className="message-avatar">🤖</div>
                <div className="message-content">
                  <div className="message-bubble">
                    <div className="typing-indicator">
                      <span></span><span></span><span></span>
                    </div>
                  </div>
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          <form className="chat-input-form" onSubmit={handleSubmit}>
            <input
              type="text"
              className="chat-input"
              placeholder="Ask Jarvis anything..."
              value={input}
              onChange={(e) => setInput(e.target.value)}
              disabled={isLoading}
            />
            <button 
              type="submit" 
              className="chat-send-btn"
              disabled={isLoading || !input.trim()}
            >
              {isLoading ? '...' : '➤'}
            </button>
          </form>
        </div>

        {tools.length > 0 && (
          <div className="tools-sidebar">
            <h4>Available Tools ({tools.length})</h4>
            <div className="tools-list-sidebar">
              {tools.slice(0, 10).map((tool, index) => (
                <button 
                  key={index} 
                  className="tool-chip"
                  onClick={() => handleToolClick(tool)}
                >
                  {tool.name}
                </button>
              ))}
              {tools.length > 10 && (
                <span className="more-tools">+{tools.length - 10} more</span>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default ChatTab;
