'use client';

/**
 * The Creative Director surface: three strategic directions, then the
 * execution plan for the one a human picked.
 *
 * Two ideas drive the layout. First, strategy and execution are different
 * decisions, so they are different screens — you choose a *route* before you
 * argue about lighting. Second, nothing here is auto-accepted: every panel
 * ends in a human action, and the specification shows which fields a person
 * changed so a later regeneration visibly cannot undo them.
 */

import { useMemo, useState } from 'react';
import { CHANNEL_LABELS } from '@/lib/api';
import type {
  Channel,
  ChannelCopy,
  CreativeDirection,
  CreativeDirectionSet,
  CreativeSpecification,
  DiversityVerdict,
} from '@/lib/api';
import { StatusBadge } from '@/components/states';

function humanise(value: string | null | undefined): string {
  return value ? value.replace(/_/g, ' ') : '—';
}

function Chip({
  children,
  tone = 'line',
  // Style families are single words and read better capitalised; constraints
  // are written sentences, which title-case mangles into "Own Copy And".
  sentence = false,
}: {
  children: React.ReactNode;
  tone?: 'line' | 'warn';
  sentence?: boolean;
}) {
  const border = tone === 'warn' ? 'border-warning/50 text-warning' : 'border-line';
  return (
    <span
      className={`rounded-full border ${border} px-2.5 py-1 text-xs ${
        sentence ? 'first-letter:uppercase' : 'capitalize'
      }`}
    >
      {children}
    </span>
  );
}

function Swatches({ palette }: { palette: string[] }) {
  if (!palette.length) return null;
  return (
    <div className="flex flex-wrap gap-1.5">
      {palette.map((hex) => (
        <span
          key={hex}
          title={hex}
          className="h-5 w-5 rounded border border-line"
          style={{ background: hex }}
        />
      ))}
    </div>
  );
}

/**
 * The distinctness check, stated plainly. It is deterministic overlap between
 * the directions' structured choices — worth saying out loud, because "these
 * are different" is a claim the user is entitled to verify.
 */
export function DiversityBadge({ verdict }: { verdict: DiversityVerdict }) {
  const overlap = Math.round(verdict.weakest_pair_similarity * 100);
  return (
    <div
      className={`rounded-md border p-3 text-xs ${
        verdict.passed ? 'border-line' : 'border-warning/40 bg-warning/5'
      }`}
    >
      <p className="font-medium">
        {verdict.passed ? 'Directions are distinct' : 'Directions overlap'}
      </p>
      <p className="mt-1 text-muted">
        Closest pair shares {overlap}% of its creative choices — angle, subject, setting,
        framing and light, compared directly rather than by wording.
      </p>
      {verdict.collisions.length ? (
        <ul className="mt-1.5 space-y-0.5 text-muted">
          {verdict.collisions.map(([a, b, score]) => (
            <li key={`${a}-${b}`}>
              Directions {a} and {b}: {Math.round(score * 100)}% overlap
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}



/** One editable line of the plan. Read-only fields render the same, without a control. */
type FieldKey = keyof CreativeSpecification;

const LONG_FIELDS: ReadonlySet<string> = new Set([
  'concept',
  'visual_story',
  'strategic_rationale',
  'composition',
  'subject',
  'environment',
  'brand_integration',
  'product_integration',
]);

function Field({
  label,
  name,
  value,
  editing,
  edited,
  draft,
  onDraft,
}: {
  label: string;
  name: FieldKey | null;
  value: string;
  editing: boolean;
  edited: boolean;
  draft: string;
  onDraft: (value: string) => void;
}) {
  const editable = editing && name !== null;
  const id = `spec-${String(name ?? label)}`;
  return (
    <div>
      <div className="flex items-baseline justify-between gap-2">
        <label htmlFor={editable ? id : undefined} className="text-[10px] uppercase tracking-wide text-muted">
          {label}
        </label>
        {edited ? (
          <span className="text-[10px] uppercase tracking-wide text-success">Yours</span>
        ) : null}
      </div>
      {editable ? (
        LONG_FIELDS.has(String(name)) ? (
          <textarea
            id={id}
            rows={3}
            value={draft}
            onChange={(event) => onDraft(event.target.value)}
            className="mt-1 w-full rounded-md border border-line bg-transparent p-2 text-sm"
          />
        ) : (
          <input
            id={id}
            value={draft}
            onChange={(event) => onDraft(event.target.value)}
            className="mt-1 w-full rounded-md border border-line bg-transparent p-2 text-sm"
          />
        )
      ) : (
        <p className="mt-0.5 text-sm">{value || '—'}</p>
      )}
    </div>
  );
}

/** label, field name (null = not editable through the API) */
type Row = readonly [string, FieldKey | null];

const SECTIONS: readonly (readonly [string, readonly Row[]])[] = [
  [
    'Concept',
    [
      ['Concept', 'concept'],
      ['Emotional angle', 'emotional_angle'],
      ['Visual metaphor', 'visual_metaphor'],
    ],
  ],
  [
    'Visual story',
    [
      ['Story', 'visual_story'],
      ['Focal point', 'focal_point'],
    ],
  ],
  [
    'Subject',
    [
      ['Subject', 'subject'],
      ['Environment', 'environment'],
      ['Product integration', 'product_integration'],
      ['People', 'people_guidance'],
    ],
  ],
  [
    'Composition',
    [
      ['Composition', 'composition'],
      ['Camera', 'camera'],
    ],
  ],
  ['Lighting', [['Lighting', 'lighting']]],
  ['Color', [['Direction', 'color_direction']]],
  ['Brand', [['Brand integration', 'brand_integration']]],
  [
    'CTA',
    [
      ['Call to action', 'cta'],
      ['How it should read', 'cta_guidance'],
    ],
  ],
];

export function SpecificationPanel({
  specification,
  direction,
  busy,
  approved,
  onSave,
  onApprove,
  onRequestChanges,
}: {
  specification: CreativeSpecification;
  direction: CreativeDirection | null;
  busy: boolean;
  approved: boolean;
  onSave: (edits: Record<string, string>) => void;
  onApprove: () => void;
  onRequestChanges: (feedback: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [feedback, setFeedback] = useState('');
  const [showFeedback, setShowFeedback] = useState(false);

  const edited = useMemo(
    () => new Set(specification.human_edited_fields),
    [specification.human_edited_fields],
  );

  function read(name: FieldKey | null): string {
    if (!name) return '';
    const value = specification[name];
    return typeof value === 'string' ? value : value == null ? '' : String(value);
  }

  function beginEditing() {
    const seed: Record<string, string> = {};
    for (const [, rows] of SECTIONS) {
      for (const [, name] of rows) {
        if (name) seed[name] = read(name);
      }
    }
    seed.headline = specification.headline;
    seed.headline_guidance = specification.headline_guidance;
    seed.subhead = specification.subhead ?? '';
    setDrafts(seed);
    setEditing(true);
  }

  function save() {
    // Only what actually changed — an untouched field must not be marked as a
    // human edit, or a regeneration would be needlessly frozen around it.
    const changed: Record<string, string> = {};
    for (const [name, value] of Object.entries(drafts)) {
      const trimmed = value.trim();
      if (trimmed !== read(name as FieldKey).trim() && trimmed !== '') changed[name] = trimmed;
    }
    setEditing(false);
    if (Object.keys(changed).length) onSave(changed);
  }

  const constraints = specification.negative_constraints;
  const typography = specification.typography_guidance;

  return (
    <section className="rounded-lg border border-line p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold">Creative Specification</h2>
          <p className="mt-1 text-xs text-muted">
            The execution plan for {direction ? `“${direction.title}”` : 'the approved direction'}.
            Version {specification.version}.
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          {approved ? (
            <span className="rounded-full border border-success/50 px-2.5 py-1 text-[10px] uppercase tracking-wide text-success">
              Approved
            </span>
          ) : editing ? (
            <>
              <button
                type="button"
                disabled={busy}
                onClick={save}
                className="rounded-md border border-line px-3 py-1.5 text-sm hover:bg-line/40 disabled:opacity-50"
              >
                Save
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
            <button
              type="button"
              disabled={busy}
              onClick={beginEditing}
              className="rounded-md border border-line px-3 py-1.5 text-sm hover:bg-line/40 disabled:opacity-50"
            >
              Edit
            </button>
          )}
        </div>
      </div>

      <div className="mt-5 rounded-md border border-line/70 p-4">
        <p className="text-[10px] uppercase tracking-wide text-muted">Copy</p>
        <div className="mt-2 space-y-3">
          <Field
            label="Headline"
            name="headline"
            value={specification.headline}
            editing={editing}
            edited={edited.has('headline')}
            draft={drafts.headline ?? ''}
            onDraft={(value) => setDrafts((d) => ({ ...d, headline: value }))}
          />
          <Field
            label="Subhead"
            name="subhead"
            value={specification.subhead ?? ''}
            editing={editing}
            edited={edited.has('subhead')}
            draft={drafts.subhead ?? ''}
            onDraft={(value) => setDrafts((d) => ({ ...d, subhead: value }))}
          />
          <Field
            label="Headline treatment"
            name="headline_guidance"
            value={specification.headline_guidance}
            editing={editing}
            edited={edited.has('headline_guidance')}
            draft={drafts.headline_guidance ?? ''}
            onDraft={(value) => setDrafts((d) => ({ ...d, headline_guidance: value }))}
          />
        </div>
      </div>

      <div className="mt-5 grid gap-5 sm:grid-cols-2">
        {SECTIONS.map(([heading, rows]) => (
          <div key={heading} className="rounded-md border border-line/70 p-4">
            <p className="text-[10px] uppercase tracking-wide text-muted">{heading}</p>
            <div className="mt-2 space-y-3">
              {rows.map(([label, name]) => (
                <Field
                  key={label}
                  label={label}
                  name={name}
                  value={read(name)}
                  editing={editing}
                  edited={name ? edited.has(name) : false}
                  draft={name ? (drafts[name] ?? '') : ''}
                  onDraft={(value) =>
                    setDrafts((d) => (name ? { ...d, [name]: value } : d))
                  }
                />
              ))}
              {heading === 'Color' ? (
                <div className="pt-1">
                  <Swatches palette={specification.palette} />
                </div>
              ) : null}
              {heading === 'Brand' && specification.regional_cues.length ? (
                <div>
                  <p className="text-[10px] uppercase tracking-wide text-muted">Regional cues</p>
                  <ul className="mt-0.5 space-y-0.5 text-sm">
                    {specification.regional_cues.map((cue) => (
                      <li key={cue}>· {cue}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </div>
          </div>
        ))}

        {/* Typography is guidance, never a font name — naming a font from a
            reference would cross the style/copy boundary (ADR-011). */}
        <div className="rounded-md border border-line/70 p-4">
          <p className="text-[10px] uppercase tracking-wide text-muted">Typography</p>
          <div className="mt-2 space-y-3 text-sm">
            <div>
              <p className="text-[10px] uppercase tracking-wide text-muted">Treatment</p>
              <p className="mt-0.5">{typography.headline_treatment ?? '—'}</p>
            </div>
            <div>
              <p className="text-[10px] uppercase tracking-wide text-muted">Hierarchy</p>
              <p className="mt-0.5">{typography.hierarchy ?? '—'}</p>
            </div>
            <div>
              <p className="text-[10px] uppercase tracking-wide text-muted">Headline length</p>
              <p className="mt-0.5">Up to {typography.max_headline_chars} characters</p>
            </div>
          </div>
        </div>

        <div className="rounded-md border border-line/70 p-4">
          <p className="text-[10px] uppercase tracking-wide text-muted">Constraints</p>
          <div className="mt-2 space-y-3 text-sm">
            {constraints.forbidden_elements.length ? (
              <div>
                <p className="text-[10px] uppercase tracking-wide text-muted">Must not appear</p>
                <div className="mt-1 flex flex-wrap gap-1.5">
                  {constraints.forbidden_elements.map((item) => (
                    <Chip key={item} tone="warn" sentence>
                      {item}
                    </Chip>
                  ))}
                </div>
              </div>
            ) : null}
            {constraints.forbidden_text.length ? (
              <div>
                <p className="text-[10px] uppercase tracking-wide text-muted">Claims to avoid</p>
                <ul className="mt-0.5 space-y-0.5 text-muted">
                  {constraints.forbidden_text.map((item) => (
                    <li key={item}>· {item}</li>
                  ))}
                </ul>
              </div>
            ) : null}
            {constraints.avoid_styles.length ? (
              <div>
                <p className="text-[10px] uppercase tracking-wide text-muted">Styles to avoid</p>
                <div className="mt-1 flex flex-wrap gap-1.5">
                  {constraints.avoid_styles.map((item) => (
                    <Chip key={item}>{humanise(item)}</Chip>
                  ))}
                </div>
              </div>
            ) : null}
            {!constraints.forbidden_elements.length &&
            !constraints.forbidden_text.length &&
            !constraints.avoid_styles.length ? (
              <p className="text-muted">No constraints carried over from the brand or references.</p>
            ) : null}
          </div>
        </div>
      </div>

      {approved ? (
        <p className="mt-5 rounded-md border border-success/40 bg-success/5 p-3 text-xs">
          Specification approved. Nothing has been generated — image generation is the next
          milestone, and it will start from exactly this plan.
        </p>
      ) : (
        <div className="mt-5 flex flex-wrap items-center gap-2">
          <button
            type="button"
            disabled={busy || editing}
            onClick={onApprove}
            className="rounded-md border border-line bg-line/30 px-3 py-1.5 text-sm hover:bg-line/50 disabled:opacity-50"
          >
            {busy ? 'Working…' : 'Approve Specification'}
          </button>
          <button
            type="button"
            disabled={busy || editing}
            onClick={() => setShowFeedback((open) => !open)}
            className="rounded-md border border-line px-3 py-1.5 text-sm hover:bg-line/40 disabled:opacity-50"
          >
            Back to directions
          </button>
        </div>
      )}

      {showFeedback && !approved ? (
        <div className="mt-4">
          <label htmlFor="spec-feedback" className="text-xs text-muted">
            What should the next set of directions do differently?
          </label>
          <textarea
            id="spec-feedback"
            rows={3}
            value={feedback}
            onChange={(event) => setFeedback(event.target.value)}
            className="mt-1.5 w-full rounded-md border border-line bg-transparent p-2.5 text-sm"
          />
          <button
            type="button"
            disabled={busy || !feedback.trim()}
            onClick={() => {
              onRequestChanges(feedback.trim());
              setFeedback('');
              setShowFeedback(false);
            }}
            className="mt-2 rounded-md border border-line px-3 py-1.5 text-sm hover:bg-line/40 disabled:opacity-50"
          >
            Send and rethink
          </button>
        </div>
      ) : null}
    </section>
  );
}

/**
 * Per-channel copy overrides.
 *
 * A campaign is one plan expressed differently per channel. This is where the
 * differences are written: a shorter headline for a story, a more technical
 * line for LinkedIn. An empty field means "use the campaign's default", so an
 * override is always a diff against the approved plan rather than a second
 * plan — which is what keeps one campaign one campaign.
 *
 * Only channels the **Campaign Specification** declares appear. The backend
 * refuses an undeclared one; showing it here and then refusing the save would
 * be a worse way to say the same thing.
 *
 * Overrides go through the same Gate 2 approval as every other field on this
 * object — a saved override is a new unapproved version until a human approves
 * it, exactly like editing the headline.
 */
export function ChannelCopyPanel({
  specification,
  channels,
  busy,
  approved,
  onSave,
}: {
  specification: CreativeSpecification;
  channels: Channel[];
  busy: boolean;
  approved: boolean;
  onSave: (overrides: Partial<Record<Channel, ChannelCopy>>) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [drafts, setDrafts] = useState<Partial<Record<Channel, ChannelCopy>>>({});

  if (channels.length === 0) return null;

  const stored = specification.channel_copy ?? {};

  function beginEditing() {
    const seed: Partial<Record<Channel, ChannelCopy>> = {};
    for (const channel of channels) {
      const existing = stored[channel];
      seed[channel] = {
        headline: existing?.headline ?? '',
        subhead: existing?.subhead ?? '',
        cta: existing?.cta ?? '',
      };
    }
    setDrafts(seed);
    setEditing(true);
  }

  function save() {
    // Blank means "inherit", so a blank field is omitted rather than sent as
    // an empty string — and a channel with nothing in it is dropped entirely,
    // so "no override" and "an override that overrides nothing" stay one state.
    const next: Partial<Record<Channel, ChannelCopy>> = {};
    for (const channel of channels) {
      const draft = drafts[channel];
      if (!draft) continue;
      const entry: ChannelCopy = {};
      if (draft.headline?.trim()) entry.headline = draft.headline.trim();
      if (draft.subhead?.trim()) entry.subhead = draft.subhead.trim();
      if (draft.cta?.trim()) entry.cta = draft.cta.trim();
      if (Object.keys(entry).length) next[channel] = entry;
    }
    setEditing(false);
    onSave(next);
  }

  const count = channels.filter((c) => stored[c]).length;

  return (
    <section className="mt-5 rounded-md border border-line/70 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-[10px] uppercase tracking-wide text-muted">Per-channel copy</p>
          <p className="mt-1 text-xs text-muted">
            Where a channel needs different words. Leave a field blank to use the campaign&rsquo;s
            own copy. {count > 0 ? `${count} of ${channels.length} channels overridden.` : null}
          </p>
        </div>
        {approved ? null : editing ? (
          <div className="flex shrink-0 gap-2">
            <button
              type="button"
              disabled={busy}
              onClick={save}
              className="rounded-md border border-line px-2.5 py-1 text-xs hover:bg-line/40 disabled:opacity-50"
            >
              Save
            </button>
            <button
              type="button"
              onClick={() => setEditing(false)}
              className="rounded-md border border-line px-2.5 py-1 text-xs hover:bg-line/40"
            >
              Cancel
            </button>
          </div>
        ) : (
          <button
            type="button"
            disabled={busy}
            onClick={beginEditing}
            className="shrink-0 rounded-md border border-line px-2.5 py-1 text-xs hover:bg-line/40 disabled:opacity-50"
          >
            Edit overrides
          </button>
        )}
      </div>

      <ul className="mt-3 space-y-3">
        {channels.map((channel) => {
          const override = stored[channel];
          const draft = drafts[channel];
          return (
            <li key={channel} className="rounded-md border border-line/70 p-3">
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-medium">{CHANNEL_LABELS[channel]}</span>
                {override ? <StatusBadge tone="positive">Overridden</StatusBadge> : null}
              </div>

              {editing ? (
                <div className="mt-2 space-y-2">
                  {(['headline', 'subhead', 'cta'] as const).map((leaf) => (
                    <label key={leaf} className="block">
                      <span className="text-[10px] uppercase tracking-wide text-muted">
                        {leaf === 'cta' ? 'Call to action' : leaf}
                      </span>
                      <input
                        value={draft?.[leaf] ?? ''}
                        placeholder={
                          leaf === 'headline'
                            ? specification.headline
                            : leaf === 'cta'
                              ? specification.cta
                              : (specification.subhead ?? '—')
                        }
                        onChange={(event) =>
                          setDrafts((current) => ({
                            ...current,
                            [channel]: { ...current[channel], [leaf]: event.target.value },
                          }))
                        }
                        className="mt-1 w-full rounded-md border border-line bg-transparent px-2 py-1 text-xs"
                      />
                    </label>
                  ))}
                </div>
              ) : override ? (
                <dl className="mt-2 space-y-1 text-xs">
                  {(['headline', 'subhead', 'cta'] as const).map((leaf) =>
                    override[leaf] ? (
                      <div key={leaf}>
                        <dt className="inline text-muted">
                          {leaf === 'cta' ? 'Call to action' : leaf}:{' '}
                        </dt>
                        <dd className="inline">{override[leaf]}</dd>
                      </div>
                    ) : null,
                  )}
                </dl>
              ) : (
                <p className="mt-1 text-xs text-muted">Uses the campaign&rsquo;s copy.</p>
              )}
            </li>
          );
        })}
      </ul>

      <p className="mt-3 text-xs text-muted">
        Overrides are approved at the same gate as the rest of the plan, and are not editable in
        the composition editor — a change to approved words goes through a revision.
      </p>
    </section>
  );
}
