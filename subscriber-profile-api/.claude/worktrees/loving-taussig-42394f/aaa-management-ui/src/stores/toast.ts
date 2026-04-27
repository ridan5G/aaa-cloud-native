import { create } from 'zustand'

type ToastType = 'success' | 'error' | 'info'

interface Toast {
  id:      string
  type:    ToastType
  message: string
}

interface ToastStore {
  toasts:  Toast[]
  show:    (type: ToastType, message: string) => void
  dismiss: (id: string) => void
}

export const useToasts = create<ToastStore>((set) => ({
  toasts: [],
  show(type, message) {
    const id = Math.random().toString(36).slice(2, 10)
    set(s => ({ toasts: [...s.toasts, { id, type, message }] }))
    setTimeout(() => set(s => ({ toasts: s.toasts.filter(t => t.id !== id) })), 5000)
  },
  dismiss(id) {
    set(s => ({ toasts: s.toasts.filter(t => t.id !== id) }))
  },
}))
