/// <reference types="vite/client" />

interface AppConfig {
  apiBaseUrl: string
  oidcAuthority: string
  oidcClientId: string
}

interface Window {
  APP_CONFIG?: AppConfig
}
