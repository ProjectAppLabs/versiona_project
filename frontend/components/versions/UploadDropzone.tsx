'use client';

/**
 * Two-phase upload UX (flows C1/C2 — kit 1): pick/drag a PDF → LOCAL preview
 * (zero network, rejects non-PDF and oversize before spending upload) →
 * confirm with title/message → intent + presigned PUT + complete → analysis
 * job progress (jobStore).
 */

import dynamic from 'next/dynamic';
import { useRef, useState } from 'react';

import { Modal } from '@/components/ui/Modal';
import { Skeleton } from '@/components/ui/Skeleton';
import { interpolate, useDict } from '@/lib/i18n/dictionaries';
import { useDocumentStore } from '@/lib/stores/documentStore';
import { useJobStore } from '@/lib/stores/jobStore';

const LocalPdf = dynamic(
  () => import('@/components/pdf/PdfViewer').then((m) => m.PdfViewer),
  { ssr: false, loading: () => <Skeleton className="h-64 w-full" /> }
);

const MAX_MB = Number(process.env.NEXT_PUBLIC_MAX_PDF_MB ?? 25);

interface UploadDropzoneProps {
  /** When provided, the upload adds a version to this document (C2). When
   * absent, the confirm step asks for a document title and creates it (C1). */
  documentId?: string;
  projectId?: string;
  compact?: boolean;
  onUploaded?: () => void;
}

export function UploadDropzone({ documentId, projectId, compact = false, onUploaded }: UploadDropzoneProps) {
  const t = useDict('documents');
  const common = useDict('common');
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [localError, setLocalError] = useState<string | null>(null);
  const [title, setTitle] = useState('');
  const [message, setMessage] = useState('');
  const [isDragging, setIsDragging] = useState(false);
  const upload = useDocumentStore((s) => s.upload);
  const uploadVersion = useDocumentStore((s) => s.uploadVersion);
  const createDocument = useDocumentStore((s) => s.createDocument);
  const resetUpload = useDocumentStore((s) => s.resetUpload);
  const track = useJobStore((s) => s.track);

  const pick = (candidate: File | undefined | null) => {
    setLocalError(null);
    if (!candidate) return;
    const isPdf =
      candidate.type === 'application/pdf' || candidate.name.toLowerCase().endsWith('.pdf');
    if (!isPdf) {
      setLocalError(t.onlyPdf);
      return;
    }
    if (candidate.size > MAX_MB * 1024 * 1024) {
      setLocalError(interpolate(t.tooBig, { mb: MAX_MB }));
      return;
    }
    setTitle(candidate.name.replace(/\.pdf$/i, ''));
    setFile(candidate);
  };

  const confirm = async () => {
    if (!file) return;
    let targetDocument = documentId;
    try {
      if (!targetDocument) {
        if (!projectId || !title.trim()) return;
        const created = await createDocument(projectId, title.trim());
        targetDocument = created.public_id;
      }
    } catch (err) {
      setLocalError(
        (err as { response?: { data?: { error?: string } } })?.response?.data?.error ??
          common.error
      );
      return;
    }
    const result = await uploadVersion(targetDocument, file, message.trim());
    if (result.phase === 'analyzing' && result.jobId) {
      track(result.jobId, () => {
        // Analysis finished: close the preview and refresh the list/timeline.
        closePreview();
        onUploaded?.();
      });
    }
  };

  const closePreview = () => {
    setFile(null);
    setMessage('');
    setLocalError(null);
    resetUpload();
  };

  const busy = upload.phase === 'uploading' || upload.phase === 'completing';

  return (
    <div>
      <button
        data-testid="upload-dropzone"
        type="button"
        className={`w-full rounded-2xl border-2 border-dashed px-6 text-center transition-colors ${
          compact ? 'py-6' : 'py-14'
        } ${isDragging ? 'border-primary bg-primary/5' : 'border-border bg-card hover:border-primary/60'}`}
        onClick={() => inputRef.current?.click()}
        onDragOver={(event) => {
          event.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setIsDragging(false);
          pick(event.dataTransfer.files?.[0]);
        }}
      >
        <p className="text-sm font-medium text-foreground">{t.dropHere}</p>
        <p className="mt-1 text-xs text-muted-foreground">PDF · máx {MAX_MB} MB</p>
      </button>
      <input
        ref={inputRef}
        data-testid="upload-input"
        type="file"
        accept="application/pdf,.pdf"
        className="hidden"
        onChange={(event) => {
          pick(event.target.files?.[0]);
          // Reset the value so picking the SAME file again re-fires change
          // (browsers skip the event when the value is unchanged).
          event.target.value = '';
        }}
      />
      {localError ? (
        <p data-testid="upload-local-error" role="alert" className="mt-2 text-sm text-destructive">
          {localError}
        </p>
      ) : null}

      <Modal open={file !== null} onClose={closePreview} title={t.previewTitle}>
        {file ? (
          <div className="flex max-h-[70vh] flex-col gap-4 overflow-y-auto pr-1">
            <div className="rounded-xl bg-muted/40 p-2">
              <LocalPdf file={file} maxPages={2} width={420} />
            </div>
            {!documentId ? (
              <label className="block text-sm">
                <span className="text-muted-foreground">{t.documentTitle}</span>
                <input
                  data-testid="upload-title"
                  className="mt-1 min-h-11 w-full rounded-lg border border-border bg-background px-3 py-2 text-base sm:text-sm"
                  value={title}
                  onChange={(event) => setTitle(event.target.value)}
                />
              </label>
            ) : null}
            <label className="block text-sm">
              <span className="text-muted-foreground">{t.versionMessage}</span>
              <input
                data-testid="upload-message"
                className="mt-1 min-h-11 w-full rounded-lg border border-border bg-background px-3 py-2 text-base sm:text-sm"
                placeholder='p. ej. "corrige observaciones del revisor 2"'
                value={message}
                onChange={(event) => setMessage(event.target.value)}
              />
            </label>

            {upload.phase === 'uploading' || upload.phase === 'completing' ? (
              <div data-testid="upload-progress">
                <div className="h-2 overflow-hidden rounded-full bg-muted">
                  <div
                    className="h-full bg-primary transition-all"
                    style={{ width: `${upload.progress}%` }}
                  />
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  {t.uploading} {upload.progress}%
                </p>
              </div>
            ) : null}
            {upload.phase === 'analyzing' ? (
              <p data-testid="upload-analyzing" className="text-sm text-muted-foreground" aria-live="polite">
                {t.analyzing}
              </p>
            ) : null}
            {upload.phase === 'error' ? (
              <p data-testid="upload-error" role="alert" className="text-sm text-destructive">
                {upload.error}
              </p>
            ) : null}

            <div className="flex justify-end gap-2">
              <button
                className="min-h-11 rounded-full border border-border px-4 py-2 text-sm hover:bg-accent hover:text-accent-foreground"
                onClick={closePreview}
                type="button"
              >
                {common.cancel}
              </button>
              <button
                data-testid="upload-confirm"
                className="min-h-11 rounded-full bg-primary px-4 py-2 text-sm text-primary-foreground disabled:cursor-not-allowed disabled:opacity-50"
                disabled={busy || upload.phase === 'analyzing' || (!documentId && !title.trim())}
                onClick={() => void confirm()}
                type="button"
              >
                {busy ? t.uploading : t.upload}
              </button>
            </div>
          </div>
        ) : null}
      </Modal>
    </div>
  );
}
