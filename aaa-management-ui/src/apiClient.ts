import axios, { AxiosError } from 'axios'
import { config } from './config'

// In-memory token store — never persisted to localStorage/cookies
let accessToken: string | null = null
export const setAccessToken = (t: string | null) => { accessToken = t }
export const getAccessToken = () => accessToken

export const apiClient = axios.create({
  baseURL: config.apiBaseUrl,
})

apiClient.interceptors.request.use(cfg => {
  if (accessToken) {
    cfg.headers.Authorization = `Bearer ${accessToken}`
  }
  return cfg
})

// Auto-retry on 429 with exponential backoff (max 3 attempts)
apiClient.interceptors.response.use(
  res => res,
  async (err: AxiosError) => {
    const cfg = err.config as (typeof err.config & { _retryCount?: number }) | undefined
    if (!cfg) return Promise.reject(err)
    if (err.response?.status !== 429) return Promise.reject(err)

    cfg._retryCount = (cfg._retryCount ?? 0) + 1
    if (cfg._retryCount > 3) return Promise.reject(err)

    const delay = 500 * 2 ** (cfg._retryCount - 1)
    await new Promise(r => setTimeout(r, delay))
    return apiClient(cfg)
  },
)
