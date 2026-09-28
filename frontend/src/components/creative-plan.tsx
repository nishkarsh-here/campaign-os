'use client';

/**
 * THE CREATIVE PLAN.
 *
 * What the chosen direction becomes: the document every visual is generated
 * from. Called the Creative Plan throughout, because "Creative Specification"
 * is the schema's name for it and the reader is not writing the schema.
 *
 * Grouped the way a marketer reads a brief — the idea, the words, the picture,
 * the guardrails — rather than in field order. Two markers ride along, both
 * from the specification itself rather than from a constant copied out of the
 * backend:
 *
 *   `human_edited_fields` — a human changed this, and a regeneration must not
 *   quietly undo it.
 *   `locked_fields` — a revision may not change this unless the feedback
 *   explicitly asked. Locked against drift, not against people.
 */

import { useState } from 'react';
import { Button, Card, Reveal, StatusBadge, Textarea, cx } from '@/components/ui';
import { CHANNEL_LABELS, type Channel, type CreativeSpecification } from '@/lib/api';
import type { Capabilities } from '@/lib/capabilities';
import {
  ORIGIN_LABEL,
  channelPlans,
  planSections,
  type CopyOrigin,
  type PlanSection,
} from '@/lib/creative';

const ORIGIN_TONE: Record<CopyOrigin, string> = {
  default: 'text-muted',
  channel: 'text-accent',
  locked: 'text-info',
};

export function CreativePlan({
  specification,
  declaredChannels,
  approved,
  gateOpen,
  capabilities,
  busy,
  onApprove,
  onRequestChanges,
}: {
  specification: CreativeSpecification;
  /** The channels the Campaign Specification declares — the only legal keys. */
  declaredChannels: readonly Channel[];
  approved: boolean;
  /** True when Gate 2 is open and a decision is actually accepted. */
  gateOpen: boolean;
  capabilities: Capabilities;
  busy: boolean;
  onApprove: () => void;
  onRequestChanges: (feedback: string) => void;
}) {
  const groups = planSections(specification);
  const channels = channelPlans(specification, declaredChannels);

  return (
    <div className="space-y-lg">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-label uppercase text-muted">Version {specification.version}</p>
          <h2 className="mt-1.5 text-h1">Creative plan</h2>
          <p className="mt-2 max-w-content text-body text-muted">
            The chosen route, worked into the document every visual is generated from.
          </p>
        </div>
        <StatusBadge tone={approved ? 'positive' : 'caution'}>
          {/* The enum never reaches the screen. */}
          {approved ? 'Creative plan approved' : 'Needs your review'}
        </StatusBadge>
      </header>

      <div className="grid gap-5 lg:grid-cols-2 lg:items-start">
        <Reveal className="space-y-5">
          <PlanGroup title="The idea" sections={groups.idea} />
          <PlanGroup title="The words" sections={groups.words} />
        </Reveal>
        <Reveal index={1} className="space-y-5">
          <PlanGroup title="The picture" sections={groups.visual} />
          <PlanGroup title="Guardrails" sections={groups.guardrails} />
          <NegativeConstraints specification={specification} />
        </Reveal>
      </div>

      <ChannelCopySection channels={channels} />

      {!approved ? (
        <PlanApproval
          gateOpen={gateOpen}
          capabilities={capabilities}
          busy={busy}
          onApprove={onApprove}
          onRequestChanges={onRequestChanges}
        />
      ) : null}
    </div>
  );
}

function PlanGroup({ title, sections }: { title: string; sections: PlanSection[] }) {
  if (sections.length === 0) return null;
  return (
    <Card>
      <h3 className="text-h3">{title}</h3>
      <dl className="mt-4 space-y-4">
        {sections.map((s) => (
          <div key={s.label}>
            <dt className="flex flex-wrap items-center gap-2">
              <span className="text-label uppercase text-muted">{s.label}</span>
              {s.edited ? (
                <span
                  title="A person changed this. A regeneration will not undo it."
                  className="text-label uppercase text-success"
                >
                  Edited by a person
                </span>
              ) : null}
              {s.locked ? (
                <span
                  title="A revision may not change this unless the feedback explicitly asks."
                  className="text-label uppercase text-info"
                >
                  Locked
                </span>
              ) : null}
            </dt>
            <dd className="mt-1 text-body">
              {Array.isArray(s.value) ? (
                <ul className="flex flex-wrap gap-1.5">
                  {s.value.map((v) => (
                    <li
                      key={v}
                      className="rounded-sm border border-line bg-line/20 px-2 py-0.5 text-caption"
                    >
                      {v}
                    </li>
                  ))}
                </ul>
              ) : (
                s.value
              )}
            </dd>
          </div>
        ))}
      </dl>
    </Card>
  );
}

/** What the creative must not do. Real `NegativeConstraints` on the plan. */
function NegativeConstraints({ specification }: { specification: CreativeSpecification }) {
  const n = specification.negative_constraints as unknown as Record<string, unknown>;
  const lists = Object.entries(n)
    .filter((entry): entry is [string, string[]] => Array.isArray(entry[1]) && entry[1].length > 0)
    .map(([key, values]) => ({ label: key.replace(/_/g, ' '), values }));
  if (lists.length === 0) return null;
  return (
    <Card className="border-l-2 border-l-danger">
      <h3 className="text-h3">What this must not do</h3>
      <p className="mt-1 text-caption text-muted">
        Carried into every prompt and checked again by the brand check.
      </p>
      <dl className="mt-4 space-y-3">
        {lists.map((l) => (
          <div key={l.label}>
            <dt className="text-label uppercase text-muted first-letter:uppercase">{l.label}</dt>
            <dd className="mt-1">
              <ul className="space-y-1">
                {l.values.map((v) => (
                  <li key={v} className="text-small">
                    {v}
                  </li>
                ))}
              </ul>
            </dd>
          </div>
        ))}
      </dl>
    </Card>
  );
}

/**
 * What each channel will actually say.
 *
 * Inheritance is the whole point: an override is a sparse diff, so most
 * channels show the campaign default and say so. A channel that overrides
 * nothing is not a channel with no words.
 */
function ChannelCopySection({
  channels,
}: {
  channels: ReturnType<typeof channelPlans>;
}) {
  if (channels.length === 0) {
    return (
      <Card>
        <h3 className="text-h3">Channel copy</h3>
        <p className="mt-2 text-body text-muted">
          The brief declares no channels yet, so there is nothing to write per channel.
        </p>
      </Card>
    );
  }
  return (
    <section aria-labelledby="channel-copy-title">
      <h3 id="channel-copy-title" className="text-h3">
        What each channel says
      </h3>
      <p className="mt-1 max-w-content text-body text-muted">
        One plan, expressed differently where a channel needs it. Anything not written for a
        channel uses the campaign default.
      </p>
      <ul className="mt-lg grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {channels.map((plan, i) => (
          <Reveal as="li" key={plan.channel} index={i}>
            <Card className="h-full">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h4 className="text-h3">{CHANNEL_LABELS[plan.channel]}</h4>
                {plan.inheritsEverything ? (
                  <span className="text-label uppercase text-muted">Inherits</span>
                ) : (
                  <StatusBadge tone="active">Tailored</StatusBadge>
                )}
              </div>
              <dl className="mt-4 space-y-3 border-t border-line pt-3">
                {plan.lines.map((line) => (
                  <div key={line.label}>
                    <dt className="flex flex-wrap items-center gap-2">
                      <span className="text-label uppercase text-muted">{line.label}</span>
                      <span className={cx('text-label uppercase', ORIGIN_TONE[line.origin])}>
                        {ORIGIN_LABEL[line.origin]}
                      </span>
                    </dt>
                    <dd className={cx('mt-1 text-small', !line.value && 'text-muted')}>
                      {/* A null subhead is a real answer: the plan has none and
                          the channel did not add one. */}
                      {line.value ?? 'Not set'}
                    </dd>
                  </div>
                ))}
              </dl>
            </Card>
          </Reveal>
        ))}
      </ul>
    </section>
  );
}

/** Gate 2. The plan is approved, or sent back with a reason. */
function PlanApproval({
  gateOpen,
  capabilities,
  busy,
  onApprove,
  onRequestChanges,
}: {
  gateOpen: boolean;
  capabilities: Capabilities;
  busy: boolean;
  onApprove: () => void;
  onRequestChanges: (feedback: string) => void;
}) {
  const [asking, setAsking] = useState(false);
  const [feedback, setFeedback] = useState('');
  const canApprove = capabilities.can('approve');
  const canRevise = capabilities.can('request_revision');

  if (!gateOpen) {
    return (
      <Card>
        <p className="text-label uppercase text-muted">Not open for a decision</p>
        <p className="mt-2 text-body text-muted">
          This plan is not currently awaiting approval. It may still be being written.
        </p>
      </Card>
    );
  }

  return (
    <Card className="border-l-2 border-l-accent">
      <p className="text-label uppercase text-accent">Creative review</p>
      <h3 className="mt-2 text-h2">Approve this plan?</h3>
      <p className="mt-2 max-w-content text-body text-muted">
        Approving locks the plan and opens generation. Every visual is built from exactly this
        document — and each one is evaluated and brand-checked against it, not against a later
        version.
      </p>

      <div className="mt-5 flex flex-wrap gap-3">
        {canApprove ? (
          <Button variant="primary" size="lg" disabled={busy} onClick={onApprove}>
            Approve the creative plan
          </Button>
        ) : (
          <p className="text-small text-muted">
            Approving the plan needs approval rights. You can still read it and ask for changes.
          </p>
        )}
        {canRevise && !asking ? (
          <Button variant="secondary" size="lg" disabled={busy} onClick={() => setAsking(true)}>
            Request changes
          </Button>
        ) : null}
      </div>

      {asking ? (
        <div className="mt-5 border-t border-line pt-5">
          <label htmlFor="plan-feedback" className="text-label uppercase text-muted">
            What needs to change?
          </label>
          <Textarea
            id="plan-feedback"
            rows={4}
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            placeholder="Keep the composition and the product placement, but make the setting feel more local."
            className="mt-2"
          />
          <p className="mt-2 text-caption text-muted">
            The plan is rewritten for the same direction. Approved facts — the call to action,
            how the brand and product appear, and the things the creative must not do — are not
            changed unless you ask for them by name.
          </p>
          <div className="mt-4 flex flex-wrap gap-3">
            <Button
              variant="primary"
              disabled={busy || !feedback.trim()}
              onClick={() => onRequestChanges(feedback.trim())}
            >
              Send it back
            </Button>
            <Button variant="ghost" disabled={busy} onClick={() => setAsking(false)}>
              Cancel
            </Button>
          </div>
        </div>
      ) : null}
    </Card>
  );
}
