'use client';

/**
 * THE CAMPAIGN COMMAND CENTRE.
 *
 * The screen you open to find out where a campaign is and what it needs from
 * you. It reads no endpoint of its own: the campaign layout already resolved
 * the summary and the creative context for the Meridian and the header, so this
 * page composes that shared state rather than issuing a second request for the
 * same thing — which is what it used to do.
 *
 * It mutates nothing. Every stage, score and verdict belongs to the screen it
 * links to, and this page is a summary of those rather than a second opinion
 * about them. That discipline is why it cannot drift from the truth.
 *
 * UI-2C moved the next action out to the persistent context rail, so it is in
 * the same place on every stage rather than living only here. What remains is
 * the fuller read: why this campaign belongs in its market, how it got here,
 * what was recommended, where every stage stands, and what has been produced.
 */

import { useEffect, useState } from 'react';
import {
  Card,
  ErrorState,
  Reveal,
  SkeletonRows,
  StatusBadge,
} from '@/components/ui';
import {
  LocalMarketPanel,
  Progress,
  ProvenanceStrip,
  provenanceNotes,
} from '@/components/command-center';
import { FinalAssetStrip, RecommendationCard } from '@/components/campaign-overview';
import { useCampaignWorkspace } from '@/lib/campaign-context';
import { resolveJourney } from '@/lib/nav';

/** Only while something is actually moving; stops the moment nothing is. */
const POLL_MS = 2500;

export default function CommandCentrePage() {
  const { campaignId, overview, overviewError, specification, creativeContext, refresh } =
    useCampaignWorkspace();

  const [polls, setPolls] = useState(0);

  // A dashboard that keeps polling a finished campaign is a dashboard nobody
  // leaves open. This stops the moment no stage is running — and it refreshes
  // the layout's summary, so the Meridian in the rail advances with the page
  // rather than going stale behind it.
  const running = overview?.stages.some((stage) => stage.state === 'RUNNING') ?? false;
  useEffect(() => {
    if (!running) return undefined;
    const timer = setTimeout(() => {
      refresh();
      setPolls((n) => n + 1);
    }, POLL_MS);
    return () => clearTimeout(timer);
  }, [running, polls, refresh]);

  // A summary that failed for a recoverable reason — a timeout, a 500 — is
  // reported with a retry. The frame handles the two unrecoverable codes, so
  // reaching here with an error means trying again is worth offering.
  if (!overview) {
    return overviewError ? (
      <ErrorState
        title="Could not load this campaign’s summary"
        message={overviewError.message}
        code={overviewError.code}
        requestId={overviewError.requestId}
        onRetry={refresh}
      />
    ) : (
      <SkeletonRows rows={5} />
    );
  }

  const nodes = resolveJourney(campaignId, overview);
  const notes = provenanceNotes(overview, creativeContext);
  const failures = overview.failed_generations;

  return (
    <div className="space-y-section">
      {/* A failure is stated at the top, above the next decision: deciding
          something while an earlier step is silently broken is worse than
          being interrupted. */}
      {failures > 0 ? (
        <ErrorState
          title={`${failures} generation${failures === 1 ? '' : 's'} failed`}
          message="Some visuals could not be produced. Open Generate to see the reason and retry."
        />
      ) : null}

      {/*
        No next-action hero here. The context rail carries it on every stage,
        in one place — two next-action affordances on one screen is how a person
        learns to trust neither. This page is the fuller read.
      */}
      <div className="grid gap-6 lg:grid-cols-[1.15fr_1fr] lg:items-start">
        <Reveal className="space-y-6">
          <LocalMarketPanel specification={specification} />
          <ProvenanceStrip notes={notes} />
        </Reveal>

        <Reveal index={1} className="space-y-6">
          <RecommendationCard view={overview} />
          <GuardianCard view={overview} />
        </Reveal>
      </div>

      <Progress nodes={nodes} />

      <FinalAssetStrip view={overview} />
    </div>
  );
}

/**
 * The brand check's verdict.
 *
 * Replaces `BrandStatusCard` here so the verdict can carry its own explanation
 * of what it means — a PASS and a NEEDS_REVISION lead to different actions and
 * the word alone does not say which.
 */
function GuardianCard({ view }: { view: Parameters<typeof provenanceNotes>[0] }) {
  const verdict = view.guardian_verdict;
  if (!verdict || view.guardian_checked === 0) {
    return (
      <Card>
        <h2 className="text-h3">Brand check</h2>
        <p className="mt-3 text-body text-muted">
          The Brand Guardian has not run for this campaign yet. It checks the work against the
          brand’s own rules before anything ships.
        </p>
      </Card>
    );
  }

  const meaning: Record<string, { tone: 'positive' | 'caution' | 'negative' | 'neutral'; text: string }> = {
    PASS: { tone: 'positive', text: 'Nothing in the work contradicts the brand’s rules.' },
    NEEDS_REVISION: {
      tone: 'caution',
      text: 'Something needs changing before this can ship. Refine explains what.',
    },
    REJECT: { tone: 'negative', text: 'The work cannot ship against this brand as it stands.' },
    UNKNOWN: { tone: 'neutral', text: 'The checks did not produce a verdict.' },
  };
  const detail = meaning[verdict] ?? meaning.UNKNOWN!;

  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-h3">Brand check</h2>
        <StatusBadge tone={detail.tone}>{verdict.replace(/_/g, ' ').toLowerCase()}</StatusBadge>
      </div>
      <p className="mt-3 text-body text-muted">{detail.text}</p>
      <p className="mt-3 text-label uppercase text-muted">
        {view.guardian_checked} {view.guardian_checked === 1 ? 'check' : 'checks'} run
      </p>
    </Card>
  );
}
