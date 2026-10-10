/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_DEV_TENANT?: string;
  readonly VITE_DEV_USER?: string;
  readonly VITE_DEV_ROLES?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
