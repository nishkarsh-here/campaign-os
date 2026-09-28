'use client';

/**
 * Brand Brain panels: documents with processing status, extracted knowledge,
 * AI proposals, and a knowledge search.
 *
 * The organising idea is that nothing the model produced is presented as fact.
 * Proposals are visibly proposals, with their source and confidence, and only
 * a human accepting one turns it into brand truth.
 */

import { useState } from 'react';
import {
  ApiError,
  api,
  isFailure,
  mediaUrl,
  type BrandAsset,
  type BrandDocument,
  type BrandFact,
  type FieldStatus,
  type KnowledgeHit,
} from '@/lib/api';
import { EmptyState, ErrorState } from '@/components/states';

const STATUS_LABEL: Record<string, string> = {
  PENDING: 'Queued',
  EXTRACTING: 'Reading text…',
  EMBEDDING: 'Indexing knowledge…',
  COMPLETED: 'Ready',
  UPLOAD_FAILED: 'Upload failed',
  EXTRACTION_FAILED: 'Could not read',
  EMBEDDING_FAILED: 'Indexing failed',
  ANALYSIS_FAILED: 'Analysis failed',
};

export function StatusPill({ status }: { status: BrandDocument['status'] }) {
  const failed = isFailure(status);
  const done = status === 'COMPLETED';
  const tone = failed
    ? 'border-danger/40 text-danger'
    : done
      ? 'border-success/40 text-success'
      : 'border-line text-muted';
  return (
    <span className={`rounded-full border px-2 py-0.5 text-xs ${tone}`}>
      {/* In-progress states get a pulse so a long ingest never looks stalled. */}
      {!failed && !done ? <span className="mr-1 animate-pulse">●</span> : null}
      {STATUS_LABEL[status] ?? status}
    </span>
  );
}

export function DocumentsPanel({
  documents,
  onUpload,
  onAddText,
  busy,
}: {
  documents: BrandDocument[];
  onUpload: (file: File) => void;
  onAddText: (title: string, content: string) => void;
  busy: boolean;
}) {
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [showText, setShowText] = useState(false);

  return (
    <section className="rounded-lg border border-line p-5">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold">Source documents</h2>
        <div className="flex gap-2">
          <label className="cursor-pointer rounded-md border border-line px-3 py-1.5 text-xs hover:bg-line/30">
            Upload PDF or text
            <input
              type="file"
              accept=".pdf,.txt,.md,application/pdf,text/plain,text/markdown"
              className="hidden"
              disabled={busy}
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) onUpload(file);
                e.target.value = '';
              }}
            />
          </label>
          <button
            onClick={() => setShowText((v) => !v)}
            className="rounded-md border border-line px-3 py-1.5 text-xs hover:bg-line/30"
          >
            Paste text
          </button>
        </div>
      </div>

      {showText ? (
        <form
          className="mt-4 space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (!title.trim() || !content.trim()) return;
            onAddText(title.trim(), content.trim());
            setTitle('');
            setContent('');
            setShowText(false);
          }}
        >
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Title"
            aria-label="Document title"
            className="w-full rounded-md border border-line bg-transparent px-3 py-2 text-sm"
          />
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder="Paste brand guidelines, product notes, positioning…"
            aria-label="Document text"
            rows={5}
            className="w-full rounded-md border border-line bg-transparent px-3 py-2 text-sm"
          />
          <button
            type="submit"
            disabled={busy || !title.trim() || !content.trim()}
            className="rounded-md bg-ink px-3 py-1.5 text-xs font-medium text-surface disabled:opacity-40"
          >
            Add to Brand Brain
          </button>
        </form>
      ) : null}

      <div className="mt-4">
        {documents.length === 0 ? (
          <EmptyState
            title="No documents yet"
            description="Upload brand guidelines or product documents. Their text becomes searchable brand knowledge."
          />
        ) : (
          <ul className="divide-y divide-line">
            {documents.map((doc) => (
              <li key={doc.id} className="flex items-start justify-between gap-4 py-3">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{doc.title}</p>
                  <p className="mt-0.5 text-xs text-muted">
                    {doc.source_type.toUpperCase()}
                    {doc.page_count ? ` · ${doc.page_count} pages` : ''}
                    {doc.chunk_count ? ` · ${doc.chunk_count} passages indexed` : ''}
                  </p>
                  {/* A failure says what went wrong, never a bare spinner. */}
                  {doc.error ? <p className="mt-1 text-xs text-danger">{doc.error}</p> : null}
                </div>
                <StatusPill status={doc.status} />
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

export function KnowledgePanel({
  brandId,
  organizationId,
  ready,
  chunkCount,
}: {
  brandId: string;
  organizationId: string | null;
  ready: boolean;
  chunkCount: number;
}) {
  const [query, setQuery] = useState('');
  const [hits, setHits] = useState<KnowledgeHit[] | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [searching, setSearching] = useState(false);

  async function search(event: React.FormEvent) {
    event.preventDefault();
    if (!query.trim()) return;
    setSearching(true);
    setError(null);
    try {
      const result = await api.queryKnowledge(brandId, organizationId, query.trim());
      setHits(result.hits);
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError('INTERNAL', String(err), 0));
    } finally {
      setSearching(false);
    }
  }

  return (
    <section className="rounded-lg border border-line p-5">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold">Brand knowledge</h2>
        <span className="text-xs text-muted">{chunkCount} passages indexed</span>
      </div>
      <p className="mt-1 text-xs text-muted">
        This is what future campaigns will retrieve from.
      </p>

      <form onSubmit={search} className="mt-4 flex gap-2">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Ask the Brand Brain — e.g. what claims are prohibited?"
          aria-label="Knowledge query"
          disabled={!ready}
          className="flex-1 rounded-md border border-line bg-transparent px-3 py-2 text-sm disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={!ready || searching || !query.trim()}
          className="rounded-md bg-ink px-4 py-2 text-sm font-medium text-surface disabled:opacity-40"
        >
          {searching ? 'Searching…' : 'Search'}
        </button>
      </form>

      <div className="mt-4">
        {!ready ? (
          <p className="text-xs text-muted">
            Add a document first — there is nothing to search yet.
          </p>
        ) : error ? (
          <ErrorState message={error.message} requestId={error.requestId} />
        ) : hits === null ? null : hits.length === 0 ? (
          <p className="text-xs text-muted">Nothing in this brand&apos;s knowledge matched.</p>
        ) : (
          <ul className="space-y-3">
            {hits.map((hit) => (
              <li key={hit.chunk_id} className="rounded-md border border-line p-3">
                <div className="flex items-center justify-between text-xs text-muted">
                  <span>
                    {hit.document_title}
                    {hit.page ? ` · page ${hit.page}` : ''}
                  </span>
                  <span>{(hit.score * 100).toFixed(0)}% match</span>
                </div>
                <p className="mt-2 whitespace-pre-wrap text-sm">{hit.content}</p>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

export function ProposalsPanel({
  facts,
  onDecide,
}: {
  facts: BrandFact[];
  onDecide: (factId: string, status: 'accepted' | 'rejected') => void;
}) {
  return (
    <section className="rounded-lg border border-line p-5">
      <h2 className="text-sm font-semibold">Proposed brand facts</h2>
      <p className="mt-1 text-xs text-muted">
        Extracted by AI from your documents. Nothing here is part of the brand until you accept it.
      </p>

      <div className="mt-4">
        {facts.length === 0 ? (
          <p className="text-xs text-muted">
            No proposals. Upload a document and the Brand Brain will suggest facts to confirm.
          </p>
        ) : (
          <ul className="space-y-3">
            {facts.map((fact) => (
              <li key={fact.id} className="rounded-md border border-line p-3">
                <div className="flex items-center justify-between text-xs text-muted">
                  <code>{fact.field}</code>
                  <span>{Math.round(fact.confidence * 100)}% confidence</span>
                </div>
                <p className="mt-1.5 text-sm">{fact.value}</p>
                {fact.provenance.document_title ? (
                  <p className="mt-1 text-xs text-muted">
                    from {fact.provenance.document_title}
                    {fact.provenance.page ? `, page ${fact.provenance.page}` : ''}
                  </p>
                ) : null}
                <div className="mt-3 flex gap-2">
                  <button
                    onClick={() => onDecide(fact.id, 'accepted')}
                    className="rounded-md border border-line px-3 py-1 text-xs hover:bg-line/40"
                  >
                    Accept
                  </button>
                  <button
                    onClick={() => onDecide(fact.id, 'rejected')}
                    className="rounded-md border border-line px-3 py-1 text-xs text-muted hover:bg-line/40"
                  >
                    Dismiss
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

export function CoveragePanel({ fields }: { fields: FieldStatus[] }) {
  const tone = {
    known: 'border-success/40 text-success',
    inferred: 'border-warning/40 text-warning',
    unknown: 'border-line text-muted',
  };
  return (
    <section className="rounded-lg border border-line p-5">
      <h2 className="text-sm font-semibold">What we know</h2>
      <p className="mt-1 text-xs text-muted">
        Confirmed, inferred but unconfirmed, or still missing.
      </p>
      <ul className="mt-4 flex flex-wrap gap-2">
        {fields.map((field) => (
          <li
            key={field.field}
            className={`rounded-full border px-2.5 py-1 text-xs ${tone[field.knowledge]}`}
          >
            {field.field.replace(/_/g, ' ').replace('.', ' · ')}
            {field.knowledge === 'inferred' ? ` (${field.proposal_count})` : ''}
          </li>
        ))}
      </ul>
    </section>
  );
}

export function AssetsPanel({
  assets,
  onUpload,
  busy,
}: {
  assets: BrandAsset[];
  onUpload: (file: File, kind: string) => void;
  busy: boolean;
}) {
  return (
    <section className="rounded-lg border border-line p-5">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold">Brand assets</h2>
        <label className="cursor-pointer rounded-md border border-line px-3 py-1.5 text-xs hover:bg-line/30">
          Upload logo
          <input
            type="file"
            accept="image/png,image/jpeg,image/webp"
            className="hidden"
            disabled={busy}
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) onUpload(file, 'logo');
              e.target.value = '';
            }}
          />
        </label>
      </div>
      <div className="mt-4">
        {assets.length === 0 ? (
          <p className="text-xs text-muted">No logos or imagery yet.</p>
        ) : (
          <ul className="flex flex-wrap gap-3">
            {assets.map((asset) => (
              <li key={asset.id} className="rounded-md border border-line p-2">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={mediaUrl(asset.url)}
                  alt={asset.filename ?? asset.kind}
                  className="h-16 w-16 object-contain"
                />
                <p className="mt-1 max-w-16 truncate text-center text-[10px] text-muted">
                  {asset.kind}
                </p>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
