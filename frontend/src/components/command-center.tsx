'use client';

/**
 * The campaign command centre's parts.
 *
 * Three ideas:
 *
 *   1. **Why this campaign belongs in this market.** The Local Market panel,
 *      the product's differentiation made visible.
 *   2. **What the system did, and what a person did.** The provenance strip.
 *   3. **Where every stage stands, and why.** The progress list.
 *
 * The next action is deliberately *not* here: UI-2C moved it to the persistent
 * context rail so it sits in one place on every stage. See
 * `components/campaign-workspace.tsx`.
 *
 * ## Every claim is checked before it is made
 *
 * The provenance strip does not narrate. Each line is emitted only when the
 * data that would justify it exists: "based on Brand Brain" needs non-empty
 * guardrails, "learned from your references" needs reference analyses,
 * "localized for X" needs a region on the specification. A strip that says
 * pleasant things unconditionally is decoration pretending to be an audit
 * trail, which is worse than having none.
 */

import Link from 'next/link';
import { Card, Fact, FactList, SectionHeader, StatusBadge, cx } from '@/components/ui';
import type { CampaignOverview, CreativeContext, CampaignSpecification } from '@/lib/api';
import { JOURNEY, journeyHref, type ResolvedNode } from '@/lib/nav';
import {
  CONFIDENCE_LABEL,
  CONFIDENCE_MEANING,
  hasMarket,
  localCues,
  marketFacts,
  type Confidence,
} from '@/lib/market';

// --------------------------------------------------------------- local market

/**
 * Why this campaign belongs in this market.
 *
 * Reads `region`, `language`, `timing_occasion`, `audience` and
 * `audience_insight` off the specification, each with the provenance the
 * specification's own `field_assertions` record — stated, from the brand,
 * inferred, or not known. `market.ts` explains the mapping.
 *
 * No field is invented and no absence is filled. A campaign in discovery shows
 * five unknowns, which is the truth about it.
 */
export function LocalMarketPanel({
  specification,
}: {
  specification: CampaignSpecification | null;
}) {
  const facts = marketFacts(specification);
  const { required, avoid } = localCues(specification);
  const known = hasMarket(facts);

  return (
    <Card>
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2 className="text-h3">Local market</h2>
        <p className="text-label uppercase text-muted">Why it belongs here</p>
      </div>

      {!known ? (
        <p className="mt-4 text-body text-muted">
          This campaign has no market yet. The brief is where the place, the language and the
          season are decided.
        </p>
      ) : (
        <>
          <FactList className="mt-5">
            {facts.map((fact) => (
              <Fact
                key={fact.key}
                label={fact.label}
                value={fact.value}
                confidence={fact.confidence}
              />
            ))}
          </FactList>

          <MarketLegend facts={facts} />

          {/* The sharp end of localization: what the creative must include to
              belong, and the line it must not cross. Both real `string[]`
              fields on the specification. */}
          {required.length > 0 || avoid.length > 0 ? (
            <div className="mt-6 space-y-4 border-t border-line pt-5">
              {required.length > 0 ? (
                <div>
                  <p className="text-label uppercase text-success">Must include</p>
                  <ul className="mt-1.5 space-y-1">
                    {required.map((item) => (
                      <li key={item} className="text-small">
                        {item}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {avoid.length > 0 ? (
                <div>
                  <p className="text-label uppercase text-danger">Must avoid</p>
                  <ul className="mt-1.5 space-y-1">
                    {avoid.map((item) => (
                      <li key={item} className="text-small">
                        {item}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </div>
          ) : null}
        </>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------- provenance

interface Note {
  /** Who did it — the distinction the product exists to preserve. */
  by: 'ai' | 'human' | 'system';
  text: string;
}

/**
 * What the provenance markers on the market facts mean.
 *
 * Rendered only for the kinds actually present above — a legend for markers
 * nobody can see is noise. It is often absent entirely, and that is itself
 * informative: a specification written directly (as the benchmark seeds them)
 * carries no `field_assertions`, so its facts are recorded without a stated
 * source, whereas one built through discovery records `stated` or `inferred`
 * per field. The panel reports that difference rather than smoothing it over.
 */
function MarketLegend({ facts }: { facts: readonly { confidence: Confidence }[] }) {
  const kinds = [...new Set(facts.map((f) => f.confidence))].filter(
    (kind) => CONFIDENCE_LABEL[kind] !== null,
  );
  if (kinds.length === 0) return null;
  return (
    <dl className="mt-5 space-y-1.5 border-t border-line pt-4">
      {kinds.map((kind) => (
        <div key={kind} className="flex flex-wrap gap-x-2">
          <dt className="text-label uppercase text-muted">{CONFIDENCE_LABEL[kind]}</dt>
          <dd className="text-caption text-muted">{CONFIDENCE_MEANING[kind]}</dd>
        </div>
      ))}
    </dl>
  );
}

/**
 * What produced this campaign's current state.
 *
 * Built by checking data, never by narrating. Each line below is guarded by the
 * field that justifies it, and the `by` marker keeps "a model proposed this"
 * and "a person approved this" visibly different — which is the whole
 * governance claim of the product.
 */
export function provenanceNotes(
  view: CampaignOverview,
  context: CreativeContext | null,
): Note[] {
  const notes: Note[] = [];
  const spec = context?.specification ?? null;

  if (view.campaign_specification_version !== null) {
    notes.push({
      by: 'human',
      text: `Brief confirmed at version ${view.campaign_specification_version}`,
    });
  }
  if (spec?.region) {
    notes.push({ by: 'ai', text: `Written for ${spec.region}` });
  }
  // Guardrails are assembled from the brand's own confirmed facts, so a
  // non-empty set is evidence the Brand Brain actually fed this campaign.
  const guardrails = context?.guardrails;
  const guarded =
    guardrails &&
    (guardrails.approved_claims.length > 0 ||
      guardrails.prohibited_claims.length > 0 ||
      guardrails.palette.length > 0 ||
      guardrails.tone_attributes.length > 0);
  if (guarded) {
    notes.push({ by: 'system', text: 'Constrained by the Brand Brain' });
  }
  if ((context?.reference_analyses.length ?? 0) > 0) {
    const n = context!.reference_analyses.length;
    notes.push({ by: 'ai', text: `Style learned from ${n} reference${n === 1 ? '' : 's'}` });
  }
  if (view.creative_specification_version !== null) {
    notes.push({
      by: view.creative_specification_approved ? 'human' : 'ai',
      text: view.creative_specification_approved
        ? `Creative plan v${view.creative_specification_version} approved by a person`
        : `Creative plan v${view.creative_specification_version} proposed, awaiting approval`,
    });
  }
  if (view.latest_batch_assets > 0) {
    notes.push({
      by: 'ai',
      text: `${view.latest_batch_assets} visual${view.latest_batch_assets === 1 ? '' : 's'} generated`,
    });
  }
  if (view.ranked.length > 0) {
    notes.push({ by: 'ai', text: `${view.ranked.length} scored against the plan and the brand` });
  }
  if (view.selected_asset_id) {
    notes.push({ by: 'human', text: 'A person selected the creative to carry forward' });
  }
  if (view.guardian_checked > 0 && view.guardian_verdict) {
    notes.push({
      by: 'system',
      text: `Brand check ran ${view.guardian_checked} check${view.guardian_checked === 1 ? '' : 's'}: ${view.guardian_verdict.replace(/_/g, ' ').toLowerCase()}`,
    });
  }
  if (view.revision_rounds > 0) {
    notes.push({
      by: 'human',
      text: `${view.revision_rounds} revision round${view.revision_rounds === 1 ? '' : 's'} requested`,
    });
  }
  if (view.composed_channels.length > 0) {
    notes.push({
      by: 'system',
      text: `Composed for ${view.composed_channels.length} channel${view.composed_channels.length === 1 ? '' : 's'}`,
    });
  }
  return notes;
}

const BY_LABEL: Record<Note['by'], string> = {
  ai: 'AI',
  human: 'Person',
  system: 'System',
};

const BY_TONE: Record<Note['by'], string> = {
  ai: 'text-info',
  human: 'text-success',
  system: 'text-muted',
};

export function ProvenanceStrip({ notes }: { notes: Note[] }) {
  if (notes.length === 0) {
    return (
      <Card>
        <h2 className="text-h3">How this campaign got here</h2>
        <p className="mt-3 text-body text-muted">
          Nothing has run yet. Once the brief is confirmed, each step records what it did here.
        </p>
      </Card>
    );
  }
  return (
    <Card>
      <h2 className="text-h3">How this campaign got here</h2>
      <p className="mt-1 text-caption text-muted">
        Every line below is recorded state, not a summary.
      </p>
      <ol className="mt-4 space-y-3">
        {notes.map((note) => (
          <li key={note.text} className="flex gap-3">
            {/* Who acted, in words rather than an icon: the difference between
                a model proposing and a person approving is the product's
                central claim and must not depend on recognising a glyph. */}
            <span
              className={cx('mt-0.5 w-14 shrink-0 text-label uppercase', BY_TONE[note.by])}
            >
              {BY_LABEL[note.by]}
            </span>
            <span className="text-small">{note.text}</span>
          </li>
        ))}
      </ol>
    </Card>
  );
}

// ------------------------------------------------------------------ progress

/**
 * The journey, restated as a checklist with the backend's own sentence per
 * stage.
 *
 * The Meridian in the rail remains the canonical navigation — this does not
 * compete with it. It exists because the rail has room for a label and a state
 * word, and the command centre has room for the sentence explaining why a stage
 * is where it is, which is the part a person actually needs when deciding what
 * to do.
 */
export function Progress({ nodes }: { nodes: readonly ResolvedNode[] }) {
  return (
    <section aria-labelledby="progress-title">
      <SectionHeader
        title={<span id="progress-title">Progress</span>}
        description="Where each stage stands, and why."
      />
      <Card padding={false} className="mt-lg">
        <ol className="divide-y divide-line">
          {nodes.map((node, i) => (
            <li key={node.id}>
              <Link
                href={node.href}
                className="flex items-start gap-4 px-5 py-4 transition-colors duration-fast hover:bg-line/20"
              >
                <span className="w-5 shrink-0 pt-0.5 text-label tabular-nums text-muted">
                  {i + 1}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-body font-medium">{node.label}</span>
                  {/* The stage's own sentence where it has one, its purpose
                      otherwise. Never both, and never invented. */}
                  <span className="mt-0.5 block text-small text-muted">
                    {node.detail ?? node.purpose}
                  </span>
                </span>
                <StageMarker node={node} />
              </Link>
            </li>
          ))}
        </ol>
      </Card>
    </section>
  );
}

function StageMarker({ node }: { node: ResolvedNode }) {
  const tone =
    node.state === 'DONE'
      ? 'positive'
      : node.state === 'RUNNING'
        ? 'active'
        : node.state === 'ATTENTION'
          ? 'caution'
          : node.state === 'FAILED'
            ? 'negative'
            : 'neutral';
  const label =
    node.state === 'available'
      ? // An optional destination has no stage state. Saying "optional" is
        // truer than borrowing "not started", which implies a gate.
        node.backing.kind === 'optional'
        ? 'Optional'
        : 'Available'
      : node.state === 'PENDING'
        ? 'Not started'
        : node.state === 'ATTENTION'
          ? 'Needs you'
          : node.state.charAt(0) + node.state.slice(1).toLowerCase();
  return <StatusBadge tone={tone}>{label}</StatusBadge>;
}

/** The journey's length, for callers that render a count. */
export const JOURNEY_LENGTH = JOURNEY.length;
export { journeyHref };
