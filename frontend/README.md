# SmartDesk Frontend

This is the frontend for the SmartDesk desktop application, built with React, TypeScript, Vite, and Electron.

## Project Structure

- `src/main.ts` - Electron main process
- `src/preload.ts` - Preload script for Electron
- `src/renderer/` - React renderer process
  - `index.html` - Main HTML file
  - `index.tsx` - React entry point
  - `App.tsx` - Main App component with routing
  - `pages/` - Individual page components
  - `services/` - API service layer
  - `styles/` - CSS files

## Pages

1. Dashboard (`/`) - Overview statistics and charts
2. Timeline (`/timeline`) - Detailed activity timeline with correction capabilities
3. Insights (`/insights`) - Analytics and visualizations
4. Report (`/report`) - Detailed reports and export functionality
5. Settings (`/settings`) - Application configuration

## Development

```bash
# Install dependencies
npm install

# Start Vite dev server
npm run dev

# Start Electron with hot reload
npm run electron:dev
```

## Building for Production

```bash
# Build the React app
npm run build

# Build Electron app
npm run electron:build
```

## Environment Variables

Create a `.env` file in the frontend directory:
```
VITE_BACKEND_URL=http://127.0.0.1:8000
```