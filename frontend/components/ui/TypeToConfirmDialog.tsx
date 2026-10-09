'use client';

/**
 * Two-step destructive confirmation (docs/audit/03 §9 — mandatory for every
 * destructive action): the user must type the exact name before confirming.
 */

import { useState } from 'react';

import { Modal } from './Modal';

interface TypeToConfirmDialogProps {
  open: boolean;
  title: string;
  description: string;
  expectedText: string;
  confirmLabel: string;
  cancelLabel?: string;
  onConfirm: (typed: string) => void;
  onClose: () => void;
  isPending?: boolean;
}

export function TypeToConfirmDialog({
  open,
  title,
  description,
  expectedText,
  confirmLabel,
  cancelLabel = 'Cancelar',
  onConfirm,
  onClose,
  isPending = false,
}: TypeToConfirmDialogProps) {
  const [typed, setTyped] = useState('');
  const matches = typed.trim() === expectedText;

  const close = () => {
    setTyped('');
    onClose();
  };

  return (
    <Modal open={open} onClose={close} title={title}>
      <p className="text-sm text-muted-foreground">{description}</p>
      <label className="mt-4 block text-sm">
        <span className="text-muted-foreground">
          Escribe <strong className="text-foreground">{expectedText}</strong> para confirmar
        </span>
        <input
          data-testid="type-to-confirm-input"
          className="mt-1 min-h-11 w-full rounded-lg border border-border bg-background px-3 py-2 text-base sm:text-sm"
          value={typed}
          onChange={(event) => setTyped(event.target.value)}
        />
      </label>
      <div className="mt-6 flex justify-end gap-2">
        <button
          className="min-h-11 rounded-full border border-border px-4 py-2 text-sm hover:bg-accent hover:text-accent-foreground"
          onClick={close}
          type="button"
        >
          {cancelLabel}
        </button>
        <button
          data-testid="type-to-confirm-submit"
          className="min-h-11 rounded-full bg-destructive px-4 py-2 text-sm text-white disabled:cursor-not-allowed disabled:opacity-50"
          disabled={!matches || isPending}
          onClick={() => onConfirm(typed.trim())}
          type="button"
        >
          {confirmLabel}
        </button>
      </div>
    </Modal>
  );
}
