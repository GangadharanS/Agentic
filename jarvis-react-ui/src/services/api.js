const API_BASE = '/api';

const DEFAULT_REPOS = [
  { full_name: 'Trimble-Connect/trimble-connect-platform', name: 'trimble-connect-platform' },
  { full_name: 'Trimble-Connect/cloud-files-service-utils', name: 'cloud-files-service-utils' },
  { full_name: 'Trimble-Connect/trimble-connect-permissions-service', name: 'trimble-connect-permissions-service' },
  { full_name: 'Trimble-Connect/trimble-connect-files-service', name: 'trimble-connect-files-service' },
  { full_name: 'Trimble-Connect/tc-api-gateway', name: 'tc-api-gateway' },
  { full_name: 'Trimble-Connect/tc-auth-service', name: 'tc-auth-service' },
  { full_name: 'Trimble-Connect/tc-project-service', name: 'tc-project-service' }
];

export const api = {
  async checkHealth() {
    const response = await fetch(`${API_BASE}/health`);
    return response.json();
  },

  async getTools() {
    const response = await fetch(`${API_BASE}/tools`);
    return response.json();
  },

  async getOpenPRs(repo) {
    const response = await fetch(`${API_BASE}/pr/open-prs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ repo })
    });
    return response.json();
  },

  async getPRsByStatus(repo, status = 'open') {
    try {
      // Try the new endpoint first
      let response = await fetch(`${API_BASE}/pr/list`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ repo, status })
      });
      
      // Check if response is JSON
      const contentType = response.headers.get('content-type');
      if (!contentType || !contentType.includes('application/json')) {
        // Fall back to open-prs endpoint for open PRs
        if (status === 'open') {
          response = await fetch(`${API_BASE}/pr/open-prs`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ repo })
          });
          const data = await response.json();
          return data;
        }
        throw new Error('API returned non-JSON response');
      }
      
      return response.json();
    } catch (error) {
      console.error('getPRsByStatus error:', error);
      // Fallback: try the open-prs endpoint
      if (status === 'open') {
        try {
          const response = await fetch(`${API_BASE}/pr/open-prs`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ repo })
          });
          return response.json();
        } catch (e) {
          return { prs: [], error: 'Failed to fetch PRs' };
        }
      }
      return { prs: [], error: error.message };
    }
  },

  async searchPR(query, searchType, repo) {
    const response = await fetch(`${API_BASE}/pr/search`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, search_type: searchType, repo })
    });
    return response.json();
  },

  async reviewPR(prId, repo) {
    const response = await fetch(`${API_BASE}/pr/review`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pr_id: prId, repo })
    });
    return response.json();
  },

  async applyComments(prId, repo, comments, action) {
    const response = await fetch(`${API_BASE}/pr/apply-comments`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pr_id: prId, repo, comments, action })
    });
    return response.json();
  },

  streamChat(message, onChunk, onComplete, onError) {
    const eventSource = new EventSource(`${API_BASE}/chat/stream?message=${encodeURIComponent(message)}`);
    
    eventSource.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.done) {
        eventSource.close();
        onComplete(data);
      } else {
        onChunk(data);
      }
    };

    eventSource.onerror = (error) => {
      eventSource.close();
      onError(error);
    };

    return () => eventSource.close();
  },

  async chat(message) {
    const response = await fetch(`${API_BASE}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message })
    });
    return response.json();
  },

  async getRepos() {
    try {
      const response = await fetch(`${API_BASE}/repos`);
      if (response.ok) {
        const data = await response.json();
        if (data.repos && data.repos.length > 0) {
          return data;
        }
      }
    } catch (error) {
      console.log('Using default repos list');
    }
    return { repos: DEFAULT_REPOS };
  },

  async generateDocs(repo, docType) {
    const response = await fetch(`${API_BASE}/docs/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ repo, doc_type: docType })
    });
    return response.json();
  },

  async generateArchitecture(repo) {
    const response = await fetch(`${API_BASE}/architecture/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ repo })
    });
    return response.json();
  },

  async getMcpServers() {
    const response = await fetch(`${API_BASE}/mcp/servers`);
    return response.json();
  },

  async getOpenBugs() {
    const response = await fetch(`${API_BASE}/bugs/open`);
    return response.json();
  },

  async analyzeBug(bugKey, repo) {
    const response = await fetch(`${API_BASE}/bugs/analyze`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ bug_key: bugKey, repo })
    });
    return response.json();
  },

  async getBranches(repo) {
    const response = await fetch(`${API_BASE}/branches?repo=${encodeURIComponent(repo)}`);
    return response.json();
  },

  async applyBugFix(bugKey, repo, baseBranch, analysis = null) {
    const response = await fetch(`${API_BASE}/bugs/apply-fix`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ bug_key: bugKey, repo, base_branch: baseBranch, analysis })
    });
    return response.json();
  },

  async raiseBugPR(bugKey, repo, branchName, baseBranch) {
    const response = await fetch(`${API_BASE}/bugs/raise-pr`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ bug_key: bugKey, repo, branch_name: branchName, base_branch: baseBranch })
    });
    return response.json();
  }
};

export default api;
