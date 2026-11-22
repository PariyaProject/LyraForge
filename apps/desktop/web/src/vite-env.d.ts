/// <reference types="vite/client" />

interface LyraForgeBootstrapConfig {
  apiBase: string;
  sessionToken: string;
}

interface Window {
  __LYRAFORGE_CONFIG__?: LyraForgeBootstrapConfig;
}
