import { useState } from 'react';
import Header from './components/Header';
import TabNavigation from './components/TabNavigation';
import ChatTab from './components/ChatTab';
import PRReviewTab from './components/PRReviewTab';
import FixingBugsTab from './components/FixingBugsTab';
import ReposTab from './components/ReposTab';
import DocsTab from './components/DocsTab';
import ConfigTab from './components/ConfigTab';
import Toast from './components/Toast';
import { useConnection } from './hooks/useConnection';
import { useToast } from './hooks/useToast';

const TABS = [
  { id: 'chat', label: 'AI Assistant', icon: '🤖' },
  { id: 'pr-review', label: 'PR Review', icon: '📝' },
  { id: 'fixing-bugs', label: 'Fixing Bugs', icon: '🐛' },
  { id: 'repos', label: 'Repos', icon: '📁' },
  { id: 'docs', label: 'Documentation', icon: '📚' },
  { id: 'config', label: 'Configuration', icon: '⚙️' }
];

function App() {
  const [activeTab, setActiveTab] = useState('chat');
  const { isConnected, tools, loading, refresh } = useConnection();
  const { toasts, showToast, removeToast } = useToast();

  const renderTabContent = () => {
    switch (activeTab) {
      case 'chat':
        return <ChatTab tools={tools} showToast={showToast} />;
      case 'pr-review':
        return <PRReviewTab showToast={showToast} />;
      case 'fixing-bugs':
        return <FixingBugsTab showToast={showToast} />;
      case 'repos':
        return <ReposTab showToast={showToast} />;
      case 'docs':
        return <DocsTab showToast={showToast} />;
      case 'config':
        return <ConfigTab showToast={showToast} isConnected={isConnected} />;
      default:
        return <ChatTab tools={tools} showToast={showToast} />;
    }
  };

  return (
    <div className="container">
      <Header isConnected={isConnected} loading={loading} onRefresh={refresh} />
      
      <TabNavigation 
        tabs={TABS} 
        activeTab={activeTab} 
        onTabChange={setActiveTab} 
      />
      
      <main className="main-content">
        {renderTabContent()}
      </main>

      <div className="toast-container">
        {toasts.map(toast => (
          <Toast 
            key={toast.id} 
            {...toast} 
            onClose={() => removeToast(toast.id)} 
          />
        ))}
      </div>
    </div>
  );
}

export default App;
