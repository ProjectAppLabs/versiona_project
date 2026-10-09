'use client';

import { useEffect } from 'react';

export function Modal({ open, onClose, title, children }: ModalProps) {
  useEffect(() => {
    if (!open) return undefined;
    function handleKeydown(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose();
    }
    document.addEventListener('keydown', handleKeydown);
    return () => document.removeEventListener('keydown', handleKeydown);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center px-4">
      <button
        aria-label="Cerrar"
        data-testid="modal-backdrop"
        className="absolute inset-0 bg-black/50"
        onClick={onClose}
        type="button"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="relative z-10 w-full max-w-lg rounded-2xl border border-border bg-card p-6 shadow-lg"
      >
        <div className="flex items-start justify-between gap-4">
          <h2 className="text-lg font-semibold text-foreground">{title}</h2>
          <button
            aria-label="Cerrar diálogo"
            className="-m-2 inline-flex min-h-11 min-w-11 shrink-0 items-center justify-center rounded text-muted-foreground hover:bg-accent hover:text-accent-foreground"
            onClick={onClose}
            type="button"
          >
            ✕
          </button>
        </div>
        <div className="mt-4">{children}</div>
      </div>
    </div>
  );
}

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
}
