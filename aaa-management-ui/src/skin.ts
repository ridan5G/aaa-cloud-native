// UI skin resolution. Reload-to-apply: callers persist + reload.
// The same logic is duplicated as a tiny inline script in index.html so the
// chosen skin is set on <html data-skin="…"> before the bundle paints.
export const SKINS = ['dark', 'light', 'cmp'] as const
export type Skin = typeof SKINS[number]

const KEY = 'aaa.skin'
export const DEFAULT_SKIN: Skin = 'dark'

export const SKIN_LABEL: Record<Skin, string> = {
  dark:  'Dark',
  light: 'Light',
  cmp:   'CMP',
}

function isSkin(v: unknown): v is Skin {
  return typeof v === 'string' && (SKINS as readonly string[]).includes(v)
}

export function getSkin(): Skin {
  const url = new URLSearchParams(window.location.search).get('skin')
  if (isSkin(url)) {
    localStorage.setItem(KEY, url)
    return url
  }
  const stored = localStorage.getItem(KEY)
  return isSkin(stored) ? stored : DEFAULT_SKIN
}

export function setSkin(skin: Skin) {
  localStorage.setItem(KEY, skin)
}
