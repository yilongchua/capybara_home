# Frontend Critical Features - Contents

Date: 2026-05-12
Scope: `frontend/`

## 1) Application Shell & Routing
- `src/app/layout.tsx`
- `src/app/workspace/layout.tsx`
- `src/app/workspace/page.tsx`
- `src/app/workspace/chats/[thread_id]/layout.tsx`
- `src/app/workspace/chats/[thread_id]/page.tsx`
- `src/components/workspace/chats/use-thread-chat.ts`

## 2) Thread Lifecycle & Streaming Chat Engine
- `src/core/threads/hooks.ts`
- `src/core/threads/queue.ts`
- `src/core/threads/use-running-run.ts`
- `src/core/threads/use-thread-remount.ts`
- `src/core/threads/utils.ts`
- `src/core/api/api-client.ts`
- `src/core/api/stream-mode.ts`

## 3) Message Rendering & Rich Output
- `src/components/workspace/messages/*`
- `src/components/ai-elements/*`
- `src/core/messages/utils.ts`
- `src/core/streamdown/*`

## 4) Artifact System (Preview, Fetch, Download)
- `src/core/artifacts/hooks.ts`
- `src/core/artifacts/loader.ts`
- `src/core/artifacts/utils.ts`
- `src/components/workspace/artifacts/*`

## 5) Dreamy Workflow Experience
- `src/app/workspace/dreamy/*`
- `src/components/workspace/dreamy/*`
- `src/core/dreamy/*`

## 6) Agents, Long-Running Tasks, Approvals, Vault, Integrations
- `src/app/workspace/agents/*`
- `src/app/workspace/approvals/page.tsx`
- `src/app/workspace/pipelines/page.tsx`
- `src/app/workspace/vault/page.tsx`
- `src/app/workspace/integrations/page.tsx`
- `src/core/control-plane/*`
- `src/core/long-running/*`

## 7) Configuration, Settings, i18n, and UX Preferences
- `src/env.js`
- `src/core/config/index.ts`
- `src/core/settings/*`
- `src/core/i18n/*`

## 8) Auth & Backend Boundary
- `src/app/api/auth/[...all]/route.ts`
- `src/server/better-auth/*`
- `src/core/*/api.ts` clients (memory, uploads, skills, mcp, models, agents, generation)

## 9) Mock/Static Mode Boundary
- `src/app/mock/api/**`
- `src/components/workspace/chats/use-thread-chat.ts`
- `src/core/config/index.ts`
- `src/core/artifacts/utils.ts`
