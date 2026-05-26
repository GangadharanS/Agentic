import { useState, useEffect } from 'react';
import api from '../services/api';
import { jsPDF } from 'jspdf';

const DOC_TYPES = [
  { value: 'readme', label: 'README' },
  { value: 'api', label: 'API Documentation' },
  { value: 'architecture', label: 'Architecture Guide' },
  { value: 'setup', label: 'Setup Guide' },
  { value: 'contributing', label: 'Contributing Guide' }
];

function DocsTab({ showToast }) {
  const [repo, setRepo] = useState('');
  const [repos, setRepos] = useState([]);
  const [loadingRepos, setLoadingRepos] = useState(true);
  const [docType, setDocType] = useState('readme');
  const [docs, setDocs] = useState('');
  const [isGenerating, setIsGenerating] = useState(false);

  useEffect(() => {
    loadRepositories();
  }, []);

  const loadRepositories = async () => {
    setLoadingRepos(true);
    try {
      const result = await api.getRepos();
      const repoList = result.repos || [];
      setRepos(repoList);
      if (repoList.length > 0 && !repo) {
        setRepo(repoList[0].full_name || repoList[0].name);
      }
    } catch (error) {
      console.error('Failed to load repositories:', error);
    } finally {
      setLoadingRepos(false);
    }
  };

  const handleGenerate = async () => {
    if (!repo.trim()) {
      showToast('Please enter a repository name', 'warning');
      return;
    }

    setIsGenerating(true);
    try {
      const result = await api.generateDocs(repo, docType);
      if (result.error) {
        showToast(result.error, 'error');
        return;
      }
      setDocs(result.documentation || result.content || '');
      showToast('Documentation generated successfully', 'success');
    } catch (error) {
      showToast('Failed to generate documentation: ' + error.message, 'error');
    } finally {
      setIsGenerating(false);
    }
  };

  const copyToClipboard = async () => {
    try {
      await navigator.clipboard.writeText(docs);
      showToast('Copied to clipboard', 'success');
    } catch (error) {
      showToast('Failed to copy', 'error');
    }
  };

  const downloadMarkdown = () => {
    const blob = new Blob([docs], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${repo.replace('/', '-')}-${docType}.md`;
    a.click();
    URL.revokeObjectURL(url);
    showToast('Downloaded as Markdown', 'success');
  };

  const downloadPDF = () => {
    try {
      const doc = new jsPDF();
      const lines = doc.splitTextToSize(docs, 180);
      let y = 20;
      
      doc.setFontSize(16);
      doc.text(`${repo} - ${docType.toUpperCase()}`, 15, y);
      y += 15;
      
      doc.setFontSize(10);
      lines.forEach((line) => {
        if (y > 280) {
          doc.addPage();
          y = 20;
        }
        doc.text(line, 15, y);
        y += 6;
      });
      
      doc.save(`${repo.replace('/', '-')}-${docType}.pdf`);
      showToast('Downloaded as PDF', 'success');
    } catch (error) {
      showToast('Failed to generate PDF: ' + error.message, 'error');
    }
  };

  return (
    <div className="tab-content active">
      <div className="docs-section">
        <h2>📚 Documentation Generator</h2>
        <p className="docs-description">
          Generate comprehensive documentation for any repository using AI.
        </p>

        <div className="docs-form">
          <div className="docs-row">
            <div className="docs-group">
              <label>Repository</label>
              <select
                value={repo}
                onChange={(e) => setRepo(e.target.value)}
                disabled={loadingRepos}
              >
                {loadingRepos ? (
                  <option value="">Loading repositories...</option>
                ) : repos.length === 0 ? (
                  <option value="">No repositories found</option>
                ) : (
                  repos.map((r, index) => (
                    <option key={index} value={r.full_name || r.name}>
                      {r.full_name || r.name}
                    </option>
                  ))
                )}
              </select>
            </div>
            <div className="docs-group">
              <label>Documentation Type</label>
              <select 
                value={docType}
                onChange={(e) => setDocType(e.target.value)}
              >
                {DOC_TYPES.map(type => (
                  <option key={type.value} value={type.value}>
                    {type.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <button 
            className="generate-docs-btn"
            onClick={handleGenerate}
            disabled={isGenerating}
          >
            {isGenerating ? (
              <><span className="loading-spinner"></span> Generating...</>
            ) : (
              <>✨ Generate Documentation</>
            )}
          </button>
        </div>

        {docs && (
          <div className="docs-output">
            <div className="docs-output-header">
              <h3>Generated Documentation</h3>
              <div className="docs-actions">
                <button className="docs-action-btn" onClick={copyToClipboard}>
                  📋 Copy
                </button>
                <button className="docs-action-btn" onClick={downloadMarkdown}>
                  📄 Download MD
                </button>
                <button className="docs-action-btn" onClick={downloadPDF}>
                  📑 Download PDF
                </button>
              </div>
            </div>
            <div className="docs-content">
              <pre>{docs}</pre>
            </div>
          </div>
        )}

        {!docs && !isGenerating && (
          <div className="empty-state">
            <div className="empty-state-icon">📝</div>
            <h3>No Documentation Generated</h3>
            <p>Enter a repository and select documentation type to get started</p>
          </div>
        )}
      </div>
    </div>
  );
}

export default DocsTab;
