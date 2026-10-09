'use client';

import { create } from 'zustand';

let toastSequence = 0;

export const useToastStore = create<ToastState>((set) => ({
  toasts: [],
  push: (message, variant = 'info') => {
    toastSequence += 1;
    const id = toastSequence;
    set((state) => ({ toasts: [...state.toasts, { id, message, variant }] }));
    return id;
  },
  dismiss: (id) =>
    set((state) => ({ toasts: state.toasts.filter((toast) => toast.id !== id) })),
  clear: () => set({ toasts: [] }),
}));

export function useToast() {
  const push = useToastStore((s) => s.push);
  const dismiss = useToastStore((s) => s.dismiss);
  return { toast: push, dismiss };
}

const TOAST_VARIANT_CLASSES: Record<ToastVariant, string> = {
  info: 'border-border bg-card text-foreground',
  success: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300',
  error: 'border-destructive/40 bg-destructive/10 text-destructive',
};

export function Toaster() {
  const toasts = useToastStore((s) => s.toasts);
  const dismiss = useToastStore((s) => s.dismiss);

  if (toasts.length === 0) return null;

  return (
    <div
      aria-live="polite"
      className="fixed bottom-4 right-4 z-50 flex w-80 flex-col gap-2"
      data-testid="toaster"
    >
      {toasts.map((toast) => (
        <div
          key={toast.id}
          role="status"
          className={`flex items-start justify-between gap-3 rounded-xl border p-3 text-sm shadow-sm ${TOAST_VARIANT_CLASSES[toast.variant]}`}
        >
          <span>{toast.message}</span>
          <button
            aria-label="Descartar aviso"
            className="-m-3 inline-flex min-h-11 min-w-11 shrink-0 items-center justify-center rounded-xl text-xs text-muted-foreground hover:text-foreground"
            onClick={() => dismiss(toast.id)}
            type="button"
          >
            ✕
          </button>
        </div>
      ))}
    </div>
  );
}

export type ToastVariant = 'info' | 'success' | 'error';

export interface Toast {
  id: number;
  message: string;
  variant: ToastVariant;
}

interface ToastState {
  toasts: Toast[];
  push: (message: string, variant?: ToastVariant) => number;
  dismiss: (id: number) => void;
  clear: () => void;
}
