/// <reference types="vite/client" />

// Typed Atlas build-time env (§8 / F11). Vite exposes only VITE_-prefixed vars.
interface ImportMetaEnv {
  // API origin. Empty = same-origin (dev proxy forwards /api → :8000). See client.ts.
  readonly VITE_API_URL?: string
  // LangSmith project URL up to the project, e.g.
  // https://smith.langchain.com/o/<org-id>/projects/p/<project-id>
  // The run deep-link is `${VITE_LANGSMITH_BASE_URL}/r/${trace_id}` (F11).
  readonly VITE_LANGSMITH_BASE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
