// Runtime config injected by Nginx via /config.js (window.APP_CONFIG).
// Falls back to Vite env vars for local development.
export const config = {
  apiBaseUrl:
    window.APP_CONFIG?.apiBaseUrl ??
    import.meta.env.VITE_API_BASE_URL ??
    '/v1',
  oidcAuthority:
    window.APP_CONFIG?.oidcAuthority ??
    import.meta.env.VITE_OIDC_AUTHORITY ??
    '',
  oidcClientId:
    window.APP_CONFIG?.oidcClientId ??
    import.meta.env.VITE_OIDC_CLIENT_ID ??
    'aaa-management-ui',
}
