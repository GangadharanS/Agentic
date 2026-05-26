# Jarvis React UI

A React-based web interface for the Jarvis Agent MCP Client.

## Tech Stack

- **React 18** - UI library
- **Vite** - Build tool and dev server
- **jsPDF** - PDF generation
- **Vanilla CSS** - Styling (migrated from original template)

## Project Structure

```
jarvis-react-ui/
├── public/
├── src/
│   ├── components/
│   │   ├── Header.jsx
│   │   ├── TabNavigation.jsx
│   │   ├── ChatTab.jsx
│   │   ├── PRReviewTab.jsx
│   │   ├── ReposTab.jsx
│   │   ├── DocsTab.jsx
│   │   ├── ConfigTab.jsx
│   │   └── Toast.jsx
│   ├── hooks/
│   │   ├── useConnection.js
│   │   └── useToast.js
│   ├── services/
│   │   └── api.js
│   ├── styles/
│   │   └── App.css
│   ├── App.jsx
│   └── main.jsx
├── index.html
├── package.json
├── vite.config.js
└── README.md
```

## Installation

```bash
# Navigate to the project
cd jarvis-react-ui

# Install dependencies
npm install

# Start development server
npm run dev
```

## Development

The app runs on port 3000 by default and proxies API requests to `http://localhost:8080` (the FastAPI backend).

### Available Scripts

- `npm run dev` - Start development server
- `npm run build` - Build for production
- `npm run preview` - Preview production build

## Features

- **AI Chat** - Interactive chat with Jarvis AI
- **PR Review** - Search and review Pull Requests
- **Repositories** - Browse repos and generate architecture
- **Documentation** - Generate documentation for repositories
- **Configuration** - Manage MCP server connections

## Backend Integration

This React app connects to the existing FastAPI backend (`mcp_client_app/app.py`). Make sure the backend is running on port 8080.

```bash
# Start the backend
cd ../mcp_client_app
python app.py
```

## Migration Notes

This React app is a conversion of the original Jinja2 template (`mcp_client_app/templates/index.html`). The functionality and styling have been preserved while modernizing the architecture.

### Key Changes

1. **Component-based architecture** - UI split into reusable React components
2. **State management** - Using React hooks (useState, useEffect)
3. **API service layer** - Centralized API calls in `services/api.js`
4. **Custom hooks** - Reusable logic in `hooks/` directory
