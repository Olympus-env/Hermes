/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_HERMES_API?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
