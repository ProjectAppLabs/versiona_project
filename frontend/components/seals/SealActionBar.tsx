'use client';

/** Sealing action bar (D4): whole document or picked sections. Rendered only
 * for reviewer/admin (role hiding is the caller's duty via canSeal). */

import { useState } from 'react';

import { Modal } from '@/components/ui/Modal';
import { useToast } from '@/components/ui/toast';
import { useDict } from '@/lib/i18n/dictionaries';
import { useSealStore } from '@/lib/stores/sealStore';
import type { SectionInfo } from '@/lib/types';

interface SealActionBarProps {
  versionId: string;
  sections: SectionInfo[];
  onSealed?: () => void;
}

export function SealActionBar({ versionId, sections, onSealed }: SealActionBarProps) {
  const t = useDict('seals');
  const common = useDict('common');
  const { toast } = useToast();
  const createSeal = useSealStore((s) => s.createSeal);
  const isSubmitting = useSealStore((s) => s.isSubmitting);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [picked, setPicked] = useState<string[]>([]);

  const seal = async (coversAll: boolean) => {
    const ok = await createSeal(versionId, {
      coversAll,
      sectionKeys: coversAll ? [] : picked,
    });
    if (ok) {
      toast(common.saved, 'success');
      setPickerOpen(false);
      setPicked([]);
      onSealed?.();
    } else {
      toast(useSealStore.getState().error ?? common.error, 'error');
    }
  };

  return (
    <div data-testid="seal-action-bar" className="flex flex-wrap items-center gap-2">
      <button
        data-testid="seal-all"
        className="min-h-11 rounded-full bg-primary px-4 py-2 text-sm text-primary-foreground disabled:opacity-50"
        disabled={isSubmitting}
        onClick={() => void seal(true)}
        type="button"
      >
        {t.sealAll}
      </button>
      <button
        data-testid="seal-sections-open"
        className="min-h-11 rounded-full border border-border px-4 py-2 text-sm hover:bg-accent"
        onClick={() => setPickerOpen(true)}
        type="button"
      >
        {t.sealSections}
      </button>

      <Modal open={pickerOpen} onClose={() => setPickerOpen(false)} title={t.pickSections}>
        <div className="flex max-h-[50vh] flex-col gap-2 overflow-y-auto">
          {sections.map((section) => (
            <label
              key={section.stable_key}
              className="flex min-h-11 cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 text-sm hover:bg-accent"
            >
              <input
                data-testid={`pick-${section.stable_key}`}
                type="checkbox"
                checked={picked.includes(section.stable_key)}
                onChange={() =>
                  setPicked((current) =>
                    current.includes(section.stable_key)
                      ? current.filter((key) => key !== section.stable_key)
                      : [...current, section.stable_key]
                  )
                }
              />
              <span className="truncate">{section.heading_text}</span>
            </label>
          ))}
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <button
            className="min-h-11 rounded-full border border-border px-4 py-2 text-sm"
            onClick={() => setPickerOpen(false)}
            type="button"
          >
            {common.cancel}
          </button>
          <button
            data-testid="seal-picked"
            className="min-h-11 rounded-full bg-primary px-4 py-2 text-sm text-primary-foreground disabled:opacity-50"
            disabled={picked.length === 0 || isSubmitting}
            onClick={() => void seal(false)}
            type="button"
          >
            {t.sealSections} ({picked.length})
          </button>
        </div>
      </Modal>
    </div>
  );
}
