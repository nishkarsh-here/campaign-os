'use client';

/**
 * Campaign discovery: the conversation, the running picture of what we know,
 * and the Campaign Specification.
 *
 * It should read like a consultant taking a brief — one question at a time,
 * with a visible reason for asking — rather than a chat window. The
 * completeness rail on the right is what makes it feel like progress toward
 * something rather than an open-ended conversation.
 */

import { useState } from 'react';
import type {
  CampaignInputs,
  CampaignMessage,
  CampaignSpecification,
  FieldAssertion,
  InterviewQuestion,
} from '@/lib/api';

const CERTAINTY_LABEL: Record<string, string> = {
  stated: 'you said this',
  brand_default: 'from your brand',
  inferred: 'we inferred this',
  unresolved: 'not settled',
};

/** An AI inference is never presented as a settled fact. */
function CertaintyBadge({ assertion }: { assertion: FieldAssertion | undefined }) {
  if (!assertion) return null;
  if (assertion.edited_by_human) {
    return <span className="text-[10px] text-emerald-400">edited by you</span>;
  }
  const tone =
    assertion.certainty === 'stated'
      ? 'text-emerald-400'
      : assertion.certainty === 'inferred'
        ? 'text-amber-400'
        : 'text-muted';
  return (
    <span className={`text-[10px] ${tone}`}>
      {assertion.availability === 'not_applicable'
        ? 'not applicable'
        : CERTAINTY_LABEL[assertion.certainty]}
    </span>
  );
}

export function Conversation({
  messages,
  question,
  onAnswer,
  busy,
  complete,
}: {
  messages: CampaignMessage[];
  question: InterviewQuestion | null;
  onAnswer: (answer: string) => void;
  busy: boolean;
  complete: boolean;
}) {
  const [answer, setAnswer] = useState('');

  return (
    <section className="rounded-lg border border-line p-5">
      <h2 className="text-sm font-semibold">Discovery</h2>
      <p className="mt-1 text-xs text-muted">
        Describe the campaign in your own words. We&apos;ll ask only what we still need.
      </p>

      <ol className="mt-5 space-y-4">
        {messages.map((message) => (
          <li key={message.id} className={message.role === 'user' ? 'pl-8' : ''}>
            <p className="text-[10px] uppercase tracking-wide text-muted">
              {message.role === 'user' ? 'You' : 'Consultant'}
            </p>
            <p className="mt-1 whitespace-pre-wrap text-sm">{message.content}</p>
          </li>
        ))}
      </ol>

      {question ? (
        <div className="mt-6 rounded-md border border-line bg-line/10 p-4">
          <p className="text-sm font-medium">{question.question}</p>
          {/* A short, user-facing reason — never reasoning traces. */}
          <p className="mt-1 text-xs text-muted">{question.why}</p>
          {question.brand_default ? (
            <p className="mt-2 text-xs text-amber-400">
              Your brand says: {question.brand_default}
            </p>
          ) : null}
          {question.options.length ? (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {question.options.map((option) => (
                <button
                  key={option}
                  type="button"
                  onClick={() => setAnswer((current) => (current ? `${current}, ${option}` : option))}
                  className="rounded-full border border-line px-2.5 py-1 text-xs hover:bg-line/40"
                >
                  {option.replace(/_/g, ' ')}
                </button>
              ))}
            </div>
          ) : null}

          <form
            className="mt-4 flex gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              if (!answer.trim()) return;
              onAnswer(answer.trim());
              setAnswer('');
            }}
          >
            <input
              value={answer}
              onChange={(e) => setAnswer(e.target.value)}
              placeholder="Answer in your own words…"
              aria-label="Your answer"
              disabled={busy}
              className="flex-1 rounded-md border border-line bg-transparent px-3 py-2 text-sm"
            />
            <button
              type="submit"
              disabled={busy || !answer.trim()}
              className="rounded-md bg-ink px-4 py-2 text-sm font-medium text-surface disabled:opacity-40"
            >
              {busy ? 'Thinking…' : 'Send'}
            </button>
          </form>
        </div>
      ) : complete ? (
        <p className="mt-6 text-sm text-emerald-400">
          We have enough to draft the Campaign Specification.
        </p>
      ) : null}
    </section>
  );
}

const TRACKED: { field: string; label: string }[] = [
  { field: 'campaign_objective', label: 'Objective' },
  { field: 'product', label: 'Product' },
  { field: 'target_audience', label: 'Audience' },
  { field: 'key_message', label: 'Message' },
  { field: 'channels', label: 'Channels' },
  { field: 'cta', label: 'Call to action' },
  { field: 'desired_emotional_response', label: 'Emotional response' },
  { field: 'region', label: 'Region' },
];

export function CompletenessRail({
  known,
  missing,
}: {
  known: CampaignInputs;
  missing: string[];
}) {
  const value = (field: string): string => {
    const raw = (known as unknown as Record<string, unknown>)[field];
    if (Array.isArray(raw)) return raw.join(', ');
    return typeof raw === 'string' ? raw : '';
  };
  const answered = TRACKED.filter((t) => value(t.field)).length;

  return (
    <section className="rounded-lg border border-line p-5">
      <div className="flex items-baseline justify-between">
        <h2 className="text-sm font-semibold">What we know</h2>
        <span className="text-xs text-muted">
          {answered}/{TRACKED.length}
        </span>
      </div>
      <div className="mt-3 h-1 w-full rounded bg-line">
        <div
          className="h-1 rounded bg-emerald-500/60 transition-all"
          style={{ width: `${(answered / TRACKED.length) * 100}%` }}
        />
      </div>

      <dl className="mt-4 space-y-3">
        {TRACKED.map((tracked) => {
          const text = value(tracked.field);
          const assertion = known.assertions?.[tracked.field];
          return (
            <div key={tracked.field}>
              <dt className="flex items-center gap-2 text-[10px] uppercase tracking-wide text-muted">
                {tracked.label}
                <CertaintyBadge assertion={assertion} />
              </dt>
              <dd className="mt-0.5 text-xs">
                {text ? (
                  <span className="line-clamp-2">{text}</span>
                ) : (
                  <span className="text-muted">
                    {missing.includes(tracked.field) ? 'still to discuss' : '—'}
                  </span>
                )}
              </dd>
            </div>
          );
        })}
      </dl>
    </section>
  );
}

const SPEC_SECTIONS: { field: keyof CampaignSpecification; label: string; multiline?: boolean }[] = [
  { field: 'objective', label: 'Objective', multiline: true },
  { field: 'audience', label: 'Audience', multiline: true },
  { field: 'product', label: 'Product' },
  { field: 'key_message', label: 'Core message', multiline: true },
  { field: 'cta', label: 'Call to action' },
  { field: 'desired_emotional_response', label: 'Desired emotional response' },
  { field: 'key_offer', label: 'Key offer' },
  { field: 'region', label: 'Region' },
  { field: 'timing_occasion', label: 'Timing / occasion' },
];

export function SpecificationPanel({
  specification,
  confirmed,
  onSave,
  onConfirm,
  busy,
}: {
  specification: CampaignSpecification;
  confirmed: boolean;
  onSave: (edits: Record<string, unknown>) => void;
  onConfirm: () => void;
  busy: boolean;
}) {
  const [draft, setDraft] = useState<Record<string, string>>({});

  const current = (field: keyof CampaignSpecification): string => {
    if (field in draft) return draft[field as string] ?? '';
    const raw = specification[field];
    if (Array.isArray(raw)) return raw.join(', ');
    return typeof raw === 'string' ? raw : '';
  };

  const dirty = Object.keys(draft).length > 0;

  return (
    <section className="rounded-lg border border-line p-5">
      <div className="flex items-baseline justify-between">
        <div>
          <h2 className="text-sm font-semibold">Campaign Specification</h2>
          <p className="mt-1 text-xs text-muted">
            The source of truth for everything that follows. Edit anything that isn&apos;t right.
          </p>
        </div>
        <span className="text-xs text-muted">v{specification.version}</span>
      </div>

      <div className="mt-5 space-y-4">
        {SPEC_SECTIONS.map((section) => {
          const assertion = specification.field_assertions?.[section.field as string];
          return (
            <div key={section.field as string}>
              <label
                htmlFor={`spec-field-${String(section.field)}`}
                className="flex items-center gap-2 text-[10px] uppercase tracking-wide text-muted"
              >
                {section.label}
                <CertaintyBadge assertion={assertion} />
              </label>
              {section.multiline ? (
                <textarea
                  id={`spec-field-${String(section.field)}`}
                  rows={2}
                  value={current(section.field)}
                  disabled={confirmed}
                  onChange={(e) =>
                    setDraft((d) => ({ ...d, [section.field as string]: e.target.value }))
                  }
                  className="mt-1 w-full rounded-md border border-line bg-transparent px-3 py-2 text-sm disabled:opacity-60"
                />
              ) : (
                <input
                  id={`spec-field-${String(section.field)}`}
                  value={current(section.field)}
                  disabled={confirmed}
                  onChange={(e) =>
                    setDraft((d) => ({ ...d, [section.field as string]: e.target.value }))
                  }
                  className="mt-1 w-full rounded-md border border-line bg-transparent px-3 py-2 text-sm disabled:opacity-60"
                />
              )}
            </div>
          );
        })}

        <div>
          <p className="text-[10px] uppercase tracking-wide text-muted">Channels</p>
          <p className="mt-1 text-sm">
            {specification.channels.map((c) => c.replace(/_/g, ' ')).join(', ') || '—'}
          </p>
        </div>

        {specification.assumptions_made.length ? (
          <div className="rounded-md border border-amber-500/40 bg-amber-500/5 p-3">
            <p className="text-xs font-medium">Proceeding on assumptions</p>
            <ul className="mt-1 space-y-0.5 text-xs text-muted">
              {specification.assumptions_made.map((a) => (
                <li key={a}>{a}</li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>

      {confirmed ? (
        <p className="mt-5 text-sm text-emerald-400">
          Confirmed. Creative work begins from this specification.
        </p>
      ) : (
        <div className="mt-5 flex gap-2">
          <button
            onClick={() => {
              onSave(draft);
              setDraft({});
            }}
            disabled={busy || !dirty}
            className="rounded-md border border-line px-3 py-1.5 text-sm disabled:opacity-40"
          >
            Save edits
          </button>
          <button
            onClick={onConfirm}
            disabled={busy || dirty}
            title={dirty ? 'Save your edits first' : undefined}
            className="rounded-md bg-ink px-4 py-1.5 text-sm font-medium text-surface disabled:opacity-40"
          >
            Confirm specification
          </button>
        </div>
      )}
    </section>
  );
}
