'use client';

/**
 * REFINEMENT — the creative in front of you, and what you would change.
 *
 * The screen answers seven questions in the order a person asks them: what am
 * I looking at, what is wrong with it, what should change, what stays
 * protected, what did change, which version is this, and what happens next.
 *
 * ## The two things it is careful about
 *
 * **A version does not inherit another version's standing.** The plate on
 * screen carries the plan version it was built from, and its brand status is
 * read from checks stamped with *that* version. Approving a revision produces
 * neither a visual nor a verdict, and the copy says so rather than letting the
 * reader assume otherwise.
 *
 * **The structure is a writing aid, not a second API.** `POST /revision` takes
 * one string. The prompts below compose that string; they are not a structured
 * payload the backend never sees. Structured KEEP/CHANGE/ADD/REMOVE editing is
 * real, and it happens on the *proposed plan*, which is the only place the
 * backend accepts field-level edits (`PATCH /revision/delta`).
 */

import { useEffect, useRef, useState } from 'react';
import {
  Button,
  Card,
  Plate,
  PlateAbsent,
  SectionHeader,
  StatusBadge,
  Textarea,
  cx,
} from '@/components/ui';
import { mediaUrl, type GeneratedAssetView } from '@/lib/api';
import type { Capabilities } from '@/lib/capabilities';
import { aspectRatio, providerLabel } from '@/lib/generation';
import {
  ACTION_MEANING,
  fieldLabel as fieldLabelOf,
  type LocalizationContext,
  type ProtectedGroup,
  type RefinementState,
  type RevisionPlan,
  type VersionBrandStatus,
} from '@/lib/refinement';

// ------------------------------------------------------- the current creative

export interface CurrentCreativeFacts {
  campaign: string | null;
  brand: string | null;
  market: string | null;
  channels: string[];
  /** The plan version this plate was built from. Never guessed. */
  version: number | null;
  brandStatus: VersionBrandStatus;
}

/**
 * The work itself, and the six facts that place it.
 *
 * The plate stays the largest thing on the screen through the whole loop —
 * refinement is a judgement about a picture, and a page that shrinks the
 * picture to make room for its own controls has misunderstood the task.
 */
export function CurrentCreative({
  asset,
  facts,
  /** True when this plate was built from an older plan than the current one. */
  supersededBy,
}: {
  asset: GeneratedAssetView | null;
  facts: CurrentCreativeFacts;
  supersededBy: number | null;
}) {
  const rows: { label: string; value: string }[] = [];
  if (facts.brand) rows.push({ label: 'Brand', value: facts.brand });
  if (facts.market) rows.push({ label: 'Market', value: facts.market });
  if (facts.channels.length) rows.push({ label: 'Channels', value: facts.channels.join(', ') });

  return (
    <Card padding={false} className="overflow-hidden">
      <div className="grid gap-0 lg:grid-cols-[minmax(0,1fr)_minmax(0,22rem)]">
        <div className="bg-line/30">
          {asset ? (
            <Plate
              src={mediaUrl(asset.url)}
              alt={`The campaign's current creative, from ${providerLabel(asset.provider)}, ${asset.width} by ${asset.height} pixels`}
              ratio={aspectRatio(asset)}
            />
          ) : (
            <PlateAbsent label="No creative selected yet" />
          )}
        </div>

        <div className="min-w-0 border-t border-line p-5 sm:p-6 lg:border-l lg:border-t-0">
          <p className="text-label uppercase text-muted">The creative</p>
          <h3 className="mt-1 text-h3">{facts.campaign ?? 'This campaign'}</h3>

          <dl className="mt-5 space-y-3 border-t border-line pt-4">
            {rows.map((row) => (
              <div key={row.label}>
                <dt className="text-label uppercase text-muted">{row.label}</dt>
                <dd className="mt-0.5 text-small">{row.value}</dd>
              </div>
            ))}
            <div>
              <dt className="text-label uppercase text-muted">Built from</dt>
              <dd className="mt-0.5 text-small">
                {facts.version === null ? (
                  <span className="text-muted">Not recorded</span>
                ) : (
                  `Creative plan v${facts.version}`
                )}
              </dd>
            </div>
            <div>
              <dt className="text-label uppercase text-muted">Brand check</dt>
              <dd className="mt-1">
                <StatusBadge tone={facts.brandStatus.tone}>{facts.brandStatus.label}</StatusBadge>
              </dd>
            </div>
          </dl>

          {/*
            The live benchmark has exactly this state: a v2 plate selected
            while the approved plan is v3. Saying it plainly is the difference
            between a person knowing what they are judging and not.
          */}
          {supersededBy !== null ? (
            <p className="mt-4 border-t border-line pt-4 text-caption text-warning">
              This visual was built from an earlier plan. The campaign’s current plan is v
              {supersededBy}, and nothing has been generated from it yet.
            </p>
          ) : null}
        </div>
      </div>
    </Card>
  );
}

// ----------------------------------------------------------- asking for change

/**
 * Writing prompts, not fields.
 *
 * `POST /revision` accepts one string. These append words to that string; they
 * are product vocabulary for the kinds of thing a revision can address, not a
 * claim about what this campaign's plan currently says, and not a structured
 * payload. Naming them after real plan values would need the revised
 * specification, which the API does not project (see the backend gap note in
 * `lib/refinement.ts`).
 */
const PROMPTS: { label: string; phrase: string }[] = [
  { label: 'Lighting', phrase: 'Change the lighting so that ' },
  { label: 'Setting', phrase: 'Change the setting so that ' },
  { label: 'Composition', phrase: 'Change the composition so that ' },
  { label: 'Mood', phrase: 'Change the mood so that ' },
  { label: 'Local cues', phrase: 'Make the local context more specific by ' },
  { label: 'Keep something', phrase: 'Keep the ' },
];

export function RevisionRequest({
  busy,
  capabilities,
  attachedAsset,
  onDetach,
  onSubmit,
}: {
  busy: boolean;
  capabilities: Capabilities;
  /** The plate this feedback is about, when the brand review sent one. */
  attachedAsset: GeneratedAssetView | null;
  onDetach: () => void;
  onSubmit: (feedback: string) => void;
}) {
  const [feedback, setFeedback] = useState('');
  const box = useRef<HTMLTextAreaElement | null>(null);

  if (!capabilities.can('request_revision')) {
    return (
      <Card>
        <p className="text-body text-muted">
          Asking for a revision needs edit rights on this campaign.
        </p>
      </Card>
    );
  }

  function append(phrase: string) {
    setFeedback((current) => {
      const joined = current.trim() ? `${current.trim()} ${phrase}` : phrase;
      return joined;
    });
    box.current?.focus();
  }

  return (
    <Card>
      <SectionHeader
        level={3}
        title="What would you like to change?"
        description="Plain language is fine. Naming what to keep as well as what to change gets a tighter revision."
      />

      {/* §9 — the thread from the brand review, said out loud. */}
      {attachedAsset ? (
        <div className="arrive mt-4 flex flex-wrap items-center gap-3 rounded-md border border-accent/40 bg-accent/5 p-3">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={mediaUrl(attachedAsset.url)}
            alt={`The visual this feedback is about, from ${providerLabel(attachedAsset.provider)}`}
            className="h-12 w-12 shrink-0 rounded border border-line object-cover"
          />
          <div className="min-w-0 flex-1">
            <p className="text-label uppercase text-accent">Feedback attached to this visual</p>
            <p className="mt-0.5 text-caption text-muted">
              The revision will be recorded against it.
            </p>
          </div>
          <Button variant="ghost" size="sm" onClick={onDetach}>
            Detach
          </Button>
        </div>
      ) : null}

      <Textarea
        ref={box}
        id="revision-feedback"
        aria-label="What would you like to change?"
        rows={4}
        value={feedback}
        onChange={(event) => setFeedback(event.target.value)}
        placeholder="Example: Keep the composition and product placement, but make the environment feel more premium and locally relevant."
        className="mt-4"
      />

      <div className="mt-3">
        <p className="text-label uppercase text-muted">
          Not sure where to start? These add a phrase to your note
        </p>
        <div className="mt-2 flex flex-wrap gap-2">
          {PROMPTS.map((prompt) => (
            <button
              key={prompt.label}
              type="button"
              onClick={() => append(prompt.phrase)}
              className="rounded-full border border-line px-3 py-1 text-caption transition-colors duration-fast hover:border-accent/50 hover:text-accent"
            >
              {prompt.label}
            </button>
          ))}
        </div>
      </div>

      <div className="mt-5 flex flex-wrap items-center gap-3 border-t border-line pt-4">
        <Button
          variant="primary"
          disabled={busy || !feedback.trim()}
          onClick={() => {
            onSubmit(feedback.trim());
            setFeedback('');
          }}
        >
          {busy ? 'Reading your note…' : 'Plan the revision'}
        </Button>
        <p className="text-caption text-muted">
          You read the plan before anything runs. Nothing is generated by this step.
        </p>
      </div>
    </Card>
  );
}

// ------------------------------------------------------------- the plan

/**
 * The revision plan, as four decisions rather than a diff.
 *
 * Every row is the planner's own `reason`; none is composed here. A plan that
 * touches nothing says so — the planner declining to change anything is a real
 * answer to vague feedback, not an empty state.
 */
export function RevisionPlanView({
  plan,
  /** Shown while the plan is still a proposal. */
  headline,
}: {
  plan: RevisionPlan;
  headline?: string | null;
}) {
  const groups = [
    { action: 'CHANGE' as const, rows: plan.change },
    { action: 'ADD' as const, rows: plan.add },
    { action: 'REMOVE' as const, rows: plan.remove },
  ].filter((g) => g.rows.length > 0);

  return (
    <div className="space-y-5">
      {headline ? <p className="text-body">{headline}</p> : null}
      <p className="text-body text-muted">{plan.interpretation}</p>

      {plan.empty ? (
        <Card className="border-l-2 border-l-warning">
          <p className="text-label uppercase text-warning">Nothing would change</p>
          <p className="mt-1 text-small text-muted">
            The planner did not find a change your note clearly asked for. Naming the part you
            want different usually resolves it.
          </p>
        </Card>
      ) : null}

      {groups.map((group, groupIndex) => {
        const meaning = ACTION_MEANING[group.action];
        return (
          <section key={group.action}>
            <div className="flex items-center gap-3">
              <StatusBadge tone={meaning.tone}>{meaning.label}</StatusBadge>
              <span className="h-px flex-1 bg-line" aria-hidden="true" />
            </div>
            <ul className="mt-3 space-y-3">
              {group.rows.map((row, i) => (
                <li key={row.field}>
                  <Card
                    as="div"
                    className={cx('arrive border-l-2', BORDER[group.action])}
                    style={{ animationDelay: `${(groupIndex * 3 + i) * 40}ms` }}
                  >
                    <p className="text-body font-medium">{row.label}</p>
                    {/* The planner's sentence, never a paraphrase. */}
                    <p className="mt-1 text-small text-muted">{row.reason}</p>

                    {row.before || row.after ? (
                      <dl className="mt-3 grid gap-3 border-t border-line pt-3 sm:grid-cols-2">
                        {row.before ? (
                          <div>
                            <dt className="text-label uppercase text-muted">Now</dt>
                            <dd className="mt-0.5 text-small text-muted">{row.before}</dd>
                          </div>
                        ) : null}
                        {row.after ? (
                          <div>
                            <dt className="text-label uppercase text-muted">Proposed</dt>
                            <dd className="mt-0.5 text-small">{row.after}</dd>
                          </div>
                        ) : null}
                      </dl>
                    ) : null}
                  </Card>
                </li>
              ))}
            </ul>
          </section>
        );
      })}

      {plan.rationale ? (
        <p className="border-t border-line pt-4 text-caption text-muted">
          <span className="text-label uppercase">Why this plan </span>
          {plan.rationale}
        </p>
      ) : null}
    </div>
  );
}

const BORDER: Record<string, string> = {
  CHANGE: 'border-l-warning',
  ADD: 'border-l-success',
  REMOVE: 'border-l-danger',
};

// ------------------------------------------------------------- protection

/**
 * What a revision does not get to touch.
 *
 * The product's actual differentiator, so it is stated in full rather than
 * summarised — and only from fields the backend really reports. An empty
 * result renders nothing at all, because a reassuring panel with no data
 * behind it is worse than no panel.
 */
export function ProtectedPanel({ groups }: { groups: ProtectedGroup[] }) {
  if (!groups.length) return null;
  return (
    <Card className="border-l-2 border-l-info">
      <p className="text-label uppercase text-info">Protected by Campaign OS</p>
      <p className="mt-1 max-w-content text-small text-muted">
        These remain protected while the creative is revised.
      </p>
      <div className="mt-4 space-y-4 border-t border-line pt-4">
        {groups.map((group) => (
          <div key={group.title}>
            <p className="text-label uppercase text-muted">{group.title}</p>
            <p className="mt-0.5 text-caption text-muted">{group.detail}</p>
            <ul className="mt-2 flex flex-wrap gap-2">
              {group.items.map((item) => (
                <li
                  key={item.field}
                  className="rounded-full border border-line bg-line/20 px-3 py-1 text-caption"
                >
                  {item.label}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </Card>
  );
}

/**
 * The market context, and why a revision cannot move it.
 *
 * Structural rather than observed: a revision writes a `CreativeSpecification`
 * and these live on the campaign brief, so "the market did not change" is a
 * fact about the schema, not a hopeful reading of this particular delta.
 */
export function LocalizationPanel({ context }: { context: LocalizationContext }) {
  if (!context.known) return null;
  return (
    <Card>
      <p className="text-label uppercase text-muted">Localization preserved</p>
      <dl className="mt-3 space-y-3">
        {context.rows.map((row) => (
          <div key={row.label}>
            <dt className="text-label uppercase text-muted">{row.label}</dt>
            <dd className="mt-0.5 text-small">{row.value}</dd>
          </div>
        ))}
      </dl>

      {context.required.length ? (
        <div className="mt-4 border-t border-line pt-3">
          <p className="text-label uppercase text-muted">Must appear</p>
          <ul className="mt-1.5 space-y-1">
            {context.required.map((item) => (
              <li key={item} className="text-caption">
                {item}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {context.restricted.length ? (
        <div className="mt-3">
          <p className="text-label uppercase text-muted">Must not appear</p>
          <ul className="mt-1.5 space-y-1">
            {context.restricted.map((item) => (
              <li key={item} className="text-caption">
                {item}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <p className="mt-4 border-t border-line pt-3 text-caption text-muted">
        A revision changes the creative without changing the market context — region, language and
        audience belong to the brief, which a revision never edits.
      </p>
    </Card>
  );
}

// ----------------------------------------------------------- the loop ahead

/**
 * What happens next, as a chain rather than a sentence.
 *
 * The step everyone skips is the fourth: a new version has to be generated and
 * then checked again. Drawing the chain is the clearest way to say that an
 * approved revision is not an approved creative.
 */
export function GuardianLoop({ state }: { state: RefinementState }) {
  const steps = [
    { label: 'Your note', done: state.step !== 'feedback' },
    { label: 'Revision plan', done: state.step === 'revised' || state.step === 'regenerate' },
    { label: 'New plan version', done: state.step === 'regenerate' },
    { label: 'Generate again', done: false },
    { label: 'Brand check', done: false },
  ];
  return (
    <div>
      <p className="text-label uppercase text-muted">What happens next</p>
      <ol className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-2">
        {steps.map((step, i) => (
          <li key={step.label} className="flex items-center gap-2">
            {i > 0 ? (
              <span aria-hidden="true" className="text-muted">
                →
              </span>
            ) : null}
            <span
              className={cx(
                'rounded-full border px-3 py-1 text-caption',
                step.done ? 'border-success/40 bg-success/10 text-success' : 'border-line text-muted',
              )}
            >
              {step.label}
              {step.done ? <span className="sr-only"> — done</span> : null}
            </span>
          </li>
        ))}
      </ol>
      {state.next ? <p className="mt-3 max-w-content text-small text-muted">{state.next}</p> : null}
    </div>
  );
}

/** Focus the feedback box when the brand review sends a visual to it. */
export function useScrollIntoView(trigger: unknown) {
  const ref = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (trigger) ref.current?.scrollIntoView?.({ block: 'center' });
  }, [trigger]);
  return ref;
}

// --------------------------------------------------- the plan, with decisions

/**
 * The proposed plan, and the three things a person may do with it.
 *
 * Editing is the one place field-level structure is real: `PATCH
 * /revision/delta` accepts a per-field value, so KEEP/CHANGE/ADD/REMOVE here
 * is an actual payload rather than a shape invented for the screen. The edit
 * form carries the planner's own reason forward unchanged — a person is
 * adjusting the *value*, not rewriting why it was proposed.
 */
export function RevisionPlanCard({
  plan,
  iteration,
  fromVersion,
  busy,
  capabilities,
  onApprove,
  onEdit,
  onDiscard,
}: {
  plan: RevisionPlan;
  iteration: number;
  fromVersion: number;
  busy: boolean;
  capabilities: Capabilities;
  onApprove: () => void;
  onEdit: (changes: { field: string; reason: string; new_value: string }[]) => void;
  onDiscard: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [values, setValues] = useState<Record<string, string>>({});
  const rows = [...plan.change, ...plan.add, ...plan.remove];
  const canDecide = capabilities.can('approve');

  return (
    <Card>
      <SectionHeader
        level={3}
        title="The revision plan"
        description={`Round ${iteration}, from creative plan v${fromVersion}. Read it before it runs — what runs is exactly what is on this screen.`}
      />

      <div className="mt-5">
        {editing ? (
          <div className="space-y-3">
            {rows.map((row) => (
              <div key={row.field} className="rounded-md border border-line p-4">
                <p className="text-body font-medium">{row.label}</p>
                <p className="mt-1 text-caption text-muted">{row.reason}</p>
                <Textarea
                  id={`plan-${row.field}`}
                  aria-label={`${row.label} — proposed value`}
                  rows={2}
                  className="mt-2"
                  value={values[row.field] ?? row.after ?? ''}
                  onChange={(event) =>
                    setValues((current) => ({ ...current, [row.field]: event.target.value }))
                  }
                />
              </div>
            ))}
          </div>
        ) : (
          <RevisionPlanView plan={plan} />
        )}
      </div>

      <div className="mt-6 flex flex-wrap gap-2 border-t border-line pt-4">
        {!canDecide ? (
          <p className="text-caption text-muted">
            Approving a revision needs approval rights. The plan is readable above.
          </p>
        ) : editing ? (
          <>
            <Button
              variant="primary"
              disabled={busy}
              onClick={() => {
                onEdit(
                  rows.map((row) => ({
                    field: row.field,
                    reason: row.reason,
                    new_value: values[row.field] ?? row.after ?? '',
                  })),
                );
                setEditing(false);
              }}
            >
              Save the plan
            </Button>
            <Button variant="ghost" disabled={busy} onClick={() => setEditing(false)}>
              Cancel
            </Button>
          </>
        ) : (
          <>
            <Button variant="primary" disabled={busy} onClick={onApprove}>
              Create revised version
            </Button>
            {rows.length ? (
              <Button variant="secondary" disabled={busy} onClick={() => setEditing(true)}>
                Edit the plan
              </Button>
            ) : null}
            <Button variant="ghost" disabled={busy} onClick={onDiscard}>
              Discard
            </Button>
          </>
        )}
      </div>
    </Card>
  );
}

/**
 * The revised plan, field by field, before it becomes the campaign's.
 *
 * `RevisionView.diff` is computed by the API from the two stored versions, so
 * this is the real before and after — not the planner's proposal re-read.
 */
export function RevisedPlanCard({
  diff,
  fromVersion,
  toVersion,
  busy,
  capabilities,
  onApprove,
  onDiscard,
}: {
  diff: { field: string; label: string; before: string; after: string }[];
  fromVersion: number;
  toVersion: number | null;
  busy: boolean;
  capabilities: Capabilities;
  onApprove: () => void;
  onDiscard: () => void;
}) {
  return (
    <Card className="border-l-2 border-l-warning">
      <SectionHeader
        level={3}
        title={`Creative plan v${toVersion ?? fromVersion + 1}`}
        description={`Everything not listed here is unchanged from v${fromVersion}, which still exists exactly as it was.`}
      />

      <ul className="mt-5 space-y-3">
        {diff.map((row, i) => (
          <li
            key={row.field}
            className="arrive rounded-md border border-line p-4"
            style={{ animationDelay: `${i * 40}ms` }}
          >
            <p className="text-body font-medium">{fieldLabelOf(row.field, row.label)}</p>
            <dl className="mt-3 grid gap-3 sm:grid-cols-2">
              <div>
                <dt className="text-label uppercase text-muted">v{fromVersion}</dt>
                <dd className="mt-0.5 text-small text-muted">{row.before}</dd>
              </div>
              <div>
                <dt className="text-label uppercase text-muted">v{toVersion ?? fromVersion + 1}</dt>
                <dd className="mt-0.5 text-small">{row.after}</dd>
              </div>
            </dl>
          </li>
        ))}
      </ul>

      <div className="mt-6 flex flex-wrap gap-2 border-t border-line pt-4">
        {capabilities.can('approve') ? (
          <>
            <Button variant="primary" disabled={busy} onClick={onApprove}>
              Make this the campaign’s plan
            </Button>
            <Button variant="ghost" disabled={busy} onClick={onDiscard}>
              Discard
            </Button>
          </>
        ) : (
          <p className="text-caption text-muted">
            Accepting a revised plan needs approval rights.
          </p>
        )}
      </div>
    </Card>
  );
}
