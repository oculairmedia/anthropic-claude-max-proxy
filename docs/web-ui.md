# Web Management UI

LLMux includes a web-based management interface for remote proxy administration. Built with React, Vite, and shadcn/ui.

## Quick Start

### Build the UI
```bash
cd web
npm install
npm run build
```

The built files are output to `web/dist/` and served automatically by the proxy at `/ui/`.

### Access the UI
1. Start the proxy: `python cli.py` → Start Proxy Server
2. Open `http://localhost:8081/ui/` in your browser
3. Log in with an API key (see [Authentication](#authentication))

## Features

### Dashboard
- Real-time server status (running/stopped, bind address, port)
- Uptime tracking
- Quick view of Claude and ChatGPT authentication status
- Auto-refresh every 30 seconds

### Authentication Management
Manage OAuth tokens for both providers without using the CLI:

**Claude (Anthropic)**
- Login with OAuth (redirects to claude.ai)
- Setup long-term token (1-year validity)
- Refresh tokens manually
- Logout (clear stored tokens)

**ChatGPT (OpenAI)**
- Login with OAuth (redirects to auth.openai.com)
- Refresh tokens manually
- Logout (clear stored tokens)

### API Key Management
Full CRUD operations for proxy API keys:
- View all keys with usage statistics
- Create new keys (plaintext shown once, copy to clipboard)
- Rename existing keys
- Delete keys with confirmation

## Authentication

The Web UI requires API key authentication to prevent unauthorized access.

### First-Time Setup
1. Create an API key via the CLI:
   ```bash
   python cli.py
   # Navigate to: API Keys → Create new key
   # Copy the key (shown only once)
   ```

2. Open the Web UI at `http://localhost:8081/ui/`
3. Enter your API key on the login page
4. The key is stored in your browser's `localStorage`

### Security Notes
- API keys are sent with every request via the `X-API-Key` header
- Keys are validated server-side using timing-safe comparison
- OAuth callback URLs are exempt from auth (required for redirect flow)
- Logout clears the stored key from your browser

### Session Management
- Keys persist across browser sessions (stored in localStorage)
- Invalid keys are detected and prompt re-authentication
- Use the Logout button to clear your session

## Development

### Local Development Server
```bash
cd web
npm run dev
```

Runs on `http://localhost:5173` with hot module replacement. API requests are proxied to `http://localhost:8081`.

### Build for Production
```bash
npm run build
```

Output: `web/dist/`

### Project Structure
```
web/
├── src/
│   ├── components/ui/    # shadcn/ui components
│   ├── pages/            # Dashboard, Auth, Keys, Login
│   ├── hooks/            # useApi hook with auth
│   ├── lib/              # Utilities (cn helper)
│   ├── App.tsx           # Main app with routing
│   ├── main.tsx          # Entry point
│   └── index.css         # Tailwind v4 theme
├── public/               # Static assets
├── components.json       # shadcn/ui config
├── package.json
├── vite.config.ts
└── tsconfig.json
```

### Adding shadcn/ui Components
```bash
npx shadcn@latest add <component-name>
```

## API Endpoints

The Web UI communicates with these management API endpoints:

### Server
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/management/server/status` | Server status, uptime |

### Claude Authentication
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/management/auth/claude/status` | Token status |
| GET | `/api/management/auth/claude/login` | Start OAuth flow |
| GET | `/api/management/auth/claude/login-long-term` | Start long-term OAuth |
| GET | `/api/management/auth/claude/callback` | OAuth callback |
| POST | `/api/management/auth/claude/refresh` | Refresh tokens |
| POST | `/api/management/auth/claude/logout` | Clear tokens |

### ChatGPT Authentication
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/management/auth/chatgpt/status` | Token status |
| GET | `/api/management/auth/chatgpt/login` | Start OAuth flow |
| GET | `/api/management/auth/chatgpt/callback` | OAuth callback |
| POST | `/api/management/auth/chatgpt/refresh` | Refresh tokens |
| POST | `/api/management/auth/chatgpt/logout` | Clear tokens |

### API Keys
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/management/keys` | List all keys |
| POST | `/api/management/keys` | Create new key |
| PATCH | `/api/management/keys/{id}` | Rename key |
| DELETE | `/api/management/keys/{id}` | Delete key |

All endpoints except OAuth callbacks require the `X-API-Key` header.

## Troubleshooting

### UI not loading
- Ensure you've built the UI: `cd web && npm run build`
- Check that `web/dist/` exists and contains `index.html`
- Verify the proxy is running on the expected port

### Authentication errors
- Create an API key via CLI if you haven't already
- Ensure the key starts with `llmux-`
- Try logging out and back in
- Check browser console for detailed errors

### OAuth redirects failing
- Ensure the proxy is accessible at the callback URL
- Check that OAuth callback paths are exempt from auth
- Review proxy logs for token exchange errors

### CORS issues in development
- Use `npm run dev` which proxies API requests
- Don't open the dev server URL directly for API calls

