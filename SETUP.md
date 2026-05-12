# Setup Guide

## Prerequisites

The following tools must be installed before running `make dev`:

| Tool | Purpose | Install |
|------|---------|---------|
| `pnpm` | Frontend package manager | `npm install -g pnpm` |
| `uv` | Python package manager | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| `nginx` | Reverse proxy (port 2026) | `brew install nginx` |
| `docker` | Container sandbox (optional) | [https://www.docker.com/](https://www.docker.com/) |

## Local Development

```bash
# 1. Install missing tools
npm install -g pnpm
curl -LsSf https://astral.sh/uv/install.sh | sh
brew install nginx

# 2. Generate config files
cd /Volumes/ryan_chua/Desktop/capybara-home
make config

# 3. Edit config.yaml — add your model + API key
#    Minimum required:
#    models:
#      - name: gpt-4
#        display_name: GPT-4
#        use: langchain_openai:ChatOpenAI
#        model: gpt-4
#        api_key: $OPENAI_API_KEY

# 4. Set API keys in .env
#    OPENAI_API_KEY=your-key

# 5. Install frontend + backend dependencies
make install

# 6. Start all services
make dev
```

Access at: **http://localhost:2026**

## Docker (Alternative)

If you have Docker installed, you can skip pnpm/uv/nginx and use Docker instead:

```bash
make docker-init     # Pull sandbox image (first time only)
make docker-start    # Start all services
```

Access at: **http://localhost:2026**

## Verify Tools Are Installed

```bash
make check
```

This checks Node.js 22+, pnpm, uv, and nginx are all available.

## Service Ports

| Service | Port |
|---------|------|
| Nginx (unified entry) | 2026 |
| Frontend (Next.js) | 3000 |
| Gateway API (FastAPI) | 8001 |
| LangGraph Agent | 2024 |


Arg Valid values in docstring not found in function signature.
HTTP 400: {"detail":"Arg Valid values in docstring not found in function signature."}
