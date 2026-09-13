'use client';

/**
 * The Brand Guardian and the revision loop.
 *
 * The screen answers two questions in order: *is this acceptable for the
 * brand?*, and then *what would you change?* Each guardian verdict shows the
 * checks behind it, marking which were decided by code and which by a model —
 * because "we matched a prohibited claim" and "a model thought so" are not the
 * same kind of statement.
 *
 * The revision plan is shown before it runs, as KEEP / CHANGE / ADD / REMOVE
 * with the current value beside the proposed one. Approving is the point of no
 * ambiguity: what runs is exactly what was on the screen, because applying a
 * delta is a pure function.
 */

import { useState } from 'react';
import { mediaUrl } from '@/lib/api';
import type {
  CheckStatus,
  GuardianResultView,
  GuardianVerdict,
  GuardianView,
  RevisionView,
} from '@/lib/api';

const VERDICT_LABEL: Record<GuardianVerdict, string> = {
  PASS: 'Pass',
  NEEDS_REVISION: 'Needs revision',
  REJECT: 'Reject',
  UNKNOWN: 'Not checked',
};

const VERDICT_TONE: Record<GuardianVerdict, string> = {
  PASS: 'border-emerald-500/50 text-emerald-400',
  NEEDS_REVISION: 'border-amber-500/50 text-amber-400',
  REJECT: 'border-red-500/50 text-red-400',
  UNKNOWN: 'border-line text-muted',
};

const CHECK_MARK: Record<CheckStatus, string> = {
  PASS: '✓',
  WARN: '⚠',
  FAIL: '✕',
  NOT_APPLICABLE: '–',
};

const CHECK_TONE: Record<CheckStatus, string> = {
  PASS: 'text-emerald-400',
  WARN: 'text-amber-400',
  FAIL: 'text-red-400',
  NOT_APPLICABLE: 'text-muted',
};

function GuardianCard({
  result,
  busy,
  onRetry,
  onGiveFeedback,
}: {
  result: GuardianResultView;
  busy: boolean;
  onRetry: () => void;
  onGiveFeedback: () => void;
}) {
  const [open, setOpen] = useState(false);
  const running = result.status === 'PENDING' || result.status === 'RUNNING';

  return (
    <article className="rounded-lg border border-line p-4">
      <div className="flex items-start gap-4">
        {result.asset ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={mediaUrl(result.asset.url)}
            alt="Checked plate"
            className="h-20 w-20 shrink-0 rounded border border-line bg-line/30 object-cover"
          />
        ) : null}

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            {result.verdict ? (
              <span
                className={`rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-wide ${VERDICT_TONE[result.verdict]}`}
              >
                {VERDICT_LABEL[result.verdict]}
              </span>
            ) : (
              <span className="text-xs text-muted">
                {running ? 'Checking…' : 'Check failed'}
              </span>
            )}
            {result.asset ? (
              <span className="text-[10px] text-muted">
                {result.asset.provider} · spec v{result.specification_version}
              </span>
            ) : null}
          </div>

          {result.summary ? <p className="mt-2 text-sm">{result.summary}</p> : null}

          {running ? (
            <div className="mt-3 h-1 overflow-hidden rounded bg-line">
              <div className="h-1 w-1/3 animate-pulse rounded bg-ink/50" />
            </div>
          ) : null}

          {/* An outage must never look like brand approval. */}
          {result.error_message ? (
            <div className="mt-3 rounded-md border border-red-500/40 bg-red-500/5 p-2.5">
              <p className="text-xs">{result.error_message}</p>
              {result.error_code ? (
                <p className="mt-1 font-mono text-[10px] text-muted">{result.error_code}</p>
              ) : null}
            </div>
          ) : null}

          {result.critical_issues.length ? (
            <ul className="mt-3 space-y-0.5 text-xs">
              {result.critical_issues.map((issue) => (
                <li key={issue} className="text-red-400">
                  ⚠ {issue}
                </li>
              ))}
            </ul>
          ) : null}
          {result.warnings.length ? (
            <ul className="mt-1 space-y-0.5 text-xs text-amber-400">
              {result.warnings.map((warning) => (
                <li key={warning}>⚠ {warning}</li>
              ))}
            </ul>
          ) : null}

          <div className="mt-3 flex flex-wrap gap-2">
            {result.checks.length ? (
              <button
                type="button"
                onClick={() => setOpen(!open)}
                className="rounded-md border border-line px-3 py-1 text-xs hover:bg-line/40"
              >
                {open ? 'Hide checks' : 'Show checks'}
              </button>
            ) : null}
            {result.can_retry ? (
              <button
                type="button"
                disabled={busy}
                onClick={onRetry}
                className="rounded-md border border-line px-3 py-1 text-xs hover:bg-line/40 disabled:opacity-50"
              >
                Retry
              </button>
            ) : null}
            {result.verdict && result.verdict !== 'PASS' ? (
              <button
                type="button"
                onClick={onGiveFeedback}
                className="rounded-md border border-line px-3 py-1 text-xs hover:bg-line/40"
              >
                Give feedback
              </button>
            ) : null}
          </div>
        </div>
      </div>

      {open ? (
        <div className="mt-4 space-y-2 border-t border-line pt-4">
          {result.checks.map((check) => (
            <div key={check.check} className="text-xs">
              <div className="flex items-baseline gap-2">
                <span className={CHECK_TONE[check.status]}>{CHECK_MARK[check.status]}</span>
                <span>{check.label}</span>
                {/* Which findings are facts and which are judgements. */}
                {check.deterministic ? (
                  <span className="rounded border border-line px-1 text-[9px] uppercase tracking-wide text-muted">
                    checked
                  </span>
                ) : null}
                {check.severity ? (
                  <span className="text-[10px] text-muted">{check.severity}</span>
                ) : null}
              </div>
              {check.detail ? <p className="ml-5 text-muted">{check.detail}</p> : null}
              {check.suggested_fix ? (
                <p className="ml-5 text-muted">Fix: {check.suggested_fix}</p>
              ) : null}
            </div>
          ))}
          <p className="pt-1 text-[10px] text-muted">
            Guardian {result.guardian_version}
            {result.guardian_model ? ` (${result.guardian_model})` : ''} · judged against
            Creative Specification v{result.specification_version}
          </p>
        </div>
      ) : null}
    </article>
  );
}

export function GuardianBoard({
  view,
  busy,
  onRetry,
  onGiveFeedback,
}: {
  view: GuardianView;
  busy: boolean;
  onRetry: (resultId: string) => void;
  onGiveFeedback: (assetId: string) => void;
}) {
  if (!view.results.length) return null;
  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-semibold">Brand Guardian</h2>
        <span className="text-xs text-muted">
          Is this acceptable for the brand? · guardian {view.guardian_version}
        </span>
      </div>
      {view.results.map((result) => (
        <GuardianCard
          key={result.id}
          result={result}
          busy={busy}
          onRetry={() => onRetry(result.id)}
          onGiveFeedback={() => onGiveFeedback(result.generated_asset_id)}
        />
      ))}
    </section>
  );
}

export function FeedbackBox({
  busy,
  onSubmit,
}: {
  busy: boolean;
  onSubmit: (feedback: string) => void;
}) {
  const [feedback, setFeedback] = useState('');
  return (
    <section className="rounded-lg border border-line p-5">
      <h2 className="text-sm font-semibold">What would you change?</h2>
      <p className="mt-1 text-xs text-muted">
        Plain language is fine. Naming what to keep as well as what to change gets a tighter
        revision — the approved product, message and call to action are preserved either way.
      </p>
      <textarea
        id="revision-feedback"
        aria-label="What would you change?"
        rows={3}
        value={feedback}
        onChange={(event) => setFeedback(event.target.value)}
        placeholder="Example: Keep the composition and product placement, but make the environment feel more premium and locally relevant."
        className="mt-3 w-full rounded-md border border-line bg-transparent p-2.5 text-sm"
      />
      <button
        type="button"
        disabled={busy || !feedback.trim()}
        onClick={() => {
          onSubmit(feedback.trim());
          setFeedback('');
        }}
        className="mt-2 rounded-md border border-line bg-line/30 px-3 py-1.5 text-sm hover:bg-line/50 disabled:opacity-50"
      >
        {busy ? 'Thinking…' : 'Propose a revision'}
      </button>
    </section>
  );
}

const ACTION_TONE: Record<string, string> = {
  KEEP: 'text-muted',
  CHANGE: 'text-amber-400',
  ADD: 'text-emerald-400',
  REMOVE: 'text-red-400',
};

/** The plan, shown before it runs. */
export function ProposedRevision({
  view,
  busy,
  onApprove,
  onReject,
  onEdit,
}: {
  view: RevisionView;
  busy: boolean;
  onApprove: () => void;
  onReject: () => void;
  onEdit: (changes: { field: string; reason: string; new_value: string }[]) => void;
}) {
  const current = view.current;
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [editing, setEditing] = useState(false);
  if (!current || current.status !== 'PROPOSED') return null;

  const delta = current.delta;
  const rows = [...delta.change, ...delta.add, ...delta.remove];

  return (
    <section className="rounded-lg border border-line p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-semibold">Proposed revision</h2>
        <span className="text-xs text-muted">
          round {current.iteration} · from v{current.from_version}
        </span>
      </div>

      <p className="mt-2 text-sm">{delta.interpretation}</p>

      {/* Why this was proposed — concise, never a reasoning trace. */}
      {delta.rationale ? (
        <div className="mt-3 rounded-md border border-line/70 p-3">
          <p className="text-[10px] uppercase tracking-wide text-muted">
            Why this revision was proposed
          </p>
          <p className="mt-1 text-xs text-muted">{delta.rationale}</p>
        </div>
      ) : null}

      <div className="mt-4 space-y-3">
        {rows.map((item) => (
          <div key={item.field} className="rounded-md border border-line/70 p-3">
            <div className="flex flex-wrap items-baseline gap-2">
              <span className={`text-[10px] uppercase tracking-wide ${ACTION_TONE[item.action]}`}>
                {item.action}
              </span>
              <span className="text-sm font-medium">{item.label}</span>
            </div>
            <p className="mt-1 text-xs text-muted">{item.reason}</p>

            {item.current_value ? (
              <div className="mt-2">
                <p className="text-[10px] uppercase tracking-wide text-muted">Before</p>
                <p className="text-xs text-muted line-through decoration-muted/50">
                  {item.current_value}
                </p>
              </div>
            ) : null}
            <div className="mt-2">
              <p className="text-[10px] uppercase tracking-wide text-muted">After</p>
              {editing ? (
                <textarea
                  aria-label={`${item.label} — proposed value`}
                  rows={2}
                  value={edits[item.field] ?? item.new_value ?? ''}
                  onChange={(event) =>
                    setEdits((current) => ({ ...current, [item.field]: event.target.value }))
                  }
                  className="mt-1 w-full rounded-md border border-line bg-transparent p-2 text-xs"
                />
              ) : (
                <p className="text-xs">{item.new_value}</p>
              )}
            </div>
          </div>
        ))}
      </div>

      {delta.keep.length ? (
        <div className="mt-4">
          <p className="text-[10px] uppercase tracking-wide text-muted">
            Kept exactly as approved
          </p>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {delta.keep.map((field) => (
              <span
                key={field}
                className="rounded-full border border-line px-2 py-0.5 text-[10px] capitalize"
              >
                {field.replace(/_/g, ' ')}
              </span>
            ))}
          </div>
        </div>
      ) : null}

      <div className="mt-5 flex flex-wrap gap-2">
        {editing ? (
          <>
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                onEdit(
                  rows.map((item) => ({
                    field: item.field,
                    reason: item.reason,
                    new_value: edits[item.field] ?? item.new_value ?? '',
                  })),
                );
                setEditing(false);
              }}
              className="rounded-md border border-line px-3 py-1.5 text-sm hover:bg-line/40 disabled:opacity-50"
            >
              Save plan
            </button>
            <button
              type="button"
              onClick={() => setEditing(false)}
              className="rounded-md border border-line px-3 py-1.5 text-sm hover:bg-line/40"
            >
              Cancel
            </button>
          </>
        ) : (
          <>
            <button
              type="button"
              disabled={busy}
              onClick={onApprove}
              className="rounded-md border border-line bg-line/30 px-3 py-1.5 text-sm hover:bg-line/50 disabled:opacity-50"
            >
              Approve revision
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => setEditing(true)}
              className="rounded-md border border-line px-3 py-1.5 text-sm hover:bg-line/40 disabled:opacity-50"
            >
              Edit plan
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={onReject}
              className="rounded-md border border-line px-3 py-1.5 text-sm hover:bg-line/40 disabled:opacity-50"
            >
              Discard
            </button>
          </>
        )}
      </div>
    </section>
  );
}

/** The revised specification, field by field, before it is approved. */
export function RevisedSpecification({
  view,
  busy,
  onApprove,
  onReject,
}: {
  view: RevisionView;
  busy: boolean;
  onApprove: () => void;
  onReject: () => void;
}) {
  const current = view.current;
  if (!current || current.status !== 'APPLIED') return null;

  return (
    <section className="rounded-lg border border-line p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-semibold">Revised Creative Specification</h2>
        <span className="text-xs text-muted">
          v{current.from_version} → v{current.to_version}
        </span>
      </div>
      <p className="mt-1 text-xs text-muted">
        Everything not listed here is unchanged from v{current.from_version}, which still
        exists exactly as it was.
      </p>

      <div className="mt-4 space-y-3">
        {view.diff.map((item) => (
          <div key={item.field} className="rounded-md border border-line/70 p-3">
            <p className="text-sm font-medium">{item.label}</p>
            <div className="mt-2 grid gap-2 sm:grid-cols-2">
              <div>
                <p className="text-[10px] uppercase tracking-wide text-muted">Before</p>
                <p className="mt-0.5 text-xs text-muted">{item.before}</p>
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-wide text-muted">After</p>
                <p className="mt-0.5 text-xs">{item.after}</p>
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="mt-5 flex flex-wrap gap-2">
        <button
          type="button"
          disabled={busy}
          onClick={onApprove}
          className="rounded-md border border-line bg-line/30 px-3 py-1.5 text-sm hover:bg-line/50 disabled:opacity-50"
        >
          Approve revised specification
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={onReject}
          className="rounded-md border border-line px-3 py-1.5 text-sm hover:bg-line/40 disabled:opacity-50"
        >
          Discard
        </button>
      </div>
    </section>
  );
}

export function RevisionHistory({ view }: { view: RevisionView }) {
  const past = view.history.filter((row) => row.id !== view.current?.id);
  if (!past.length) return null;

  return (
    <section className="rounded-lg border border-line p-5">
      <h2 className="text-sm font-semibold">Revision history</h2>
      <ul className="mt-3 space-y-3">
        {past.map((row) => (
          <li key={row.id} className="rounded-md border border-line/70 p-3">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <span className="text-xs font-medium">
                Round {row.iteration} · v{row.from_version}
                {row.to_version ? ` → v${row.to_version}` : ''}
              </span>
              <span className="text-[10px] uppercase tracking-wide text-muted">
                {row.status.toLowerCase().replace('_', ' ')}
              </span>
            </div>
            <p className="mt-1 text-xs text-muted">“{row.user_feedback}”</p>
            {row.changed_fields.length ? (
              <p className="mt-1 text-[10px] text-muted">
                Changed: {row.changed_fields.map((f) => f.replace(/_/g, ' ')).join(', ')}
              </p>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}
