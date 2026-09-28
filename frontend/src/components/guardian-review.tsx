'use client';

/**
 * BRAND REVIEW — the Brand Guardian, as governance rather than validation.
 *
 * The question is "does this creative stay inside the brand's rules?", and the
 * answer is a list of named checks with what each one found.
 *
 * ## Two things this screen is careful about
 *
 * **The verdict follows from the checks.** `decide_verdict` turns findings into
 * PASS / NEEDS_REVISION / REJECT in code, and a model never returns a verdict.
 * The tally is shown beside it so the chain is visible.
 *
 * **A check decided by code is not a check decided by a model.**
 * `GuardianCheckView.deterministic` records which is which, and the two carry
 * different weight: a prohibited claim found by string matching is a fact,
 * while a tone judgement is an opinion. The screen says which it is.
 *
 * "Why it matters" has no backend field. The sentences here are Campaign OS's
 * own, shown under our name, never beside the model's finding as though it
 * said them.
 */

import {
  Button,
  Card,
  EmptyState,
  Plate,
  PlateAbsent,
  Reveal,
  StatusBadge,
  cx,
  type Tone,
} from '@/components/ui';
import { mediaUrl, type GuardianResultView, type GuardianView } from '@/lib/api';
import type { Capabilities } from '@/lib/capabilities';
import { checkMeaning, checkTally, orderChecks, verdictMeaning, whyItMatters } from '@/lib/review';
import { aspectRatio, providerLabel } from '@/lib/generation';

/**
 * Whether a sentence is just the verdict said again.
 *
 * Compared on the words rather than byte-for-byte, because the two come from
 * different places: the backend writes "Within the brand's rules." with a
 * straight apostrophe, and the label here is typeset.
 */
function restates(summary: string, label: string): boolean {
  const words = (text: string) =>
    text
      .toLowerCase()
      .replace(/[\u2018\u2019']/g, '')
      .replace(/[^a-z0-9]+/g, ' ')
      .trim();
  return !summary.trim() || words(summary) === words(label);
}

/**
 * The verdict's colour. A record rather than an interpolated class name,
 * because Tailwind only emits the classes it can see written down.
 */
const VERDICT_INK: Record<Tone, string> = {
  positive: 'text-success',
  caution: 'text-warning',
  negative: 'text-danger',
  active: 'text-info',
  neutral: 'text-muted',
};

export function GuardianReview({
  view,
  capabilities,
  busy,
  pending,
  onCheck,
  onRetry,
  onGiveFeedback,
}: {
  view: GuardianView;
  capabilities: Capabilities;
  busy: boolean;
  /** A check is in flight. Distinct from `busy`, which is our own request. */
  pending: boolean;
  /**
   * Start a check. `assetIds` narrows it to specific visuals, which is what
   * "check the remaining two" has to mean — omitting it re-checks every one.
   */
  onCheck: (assetIds?: string[]) => void;
  onRetry: (resultId: string) => void;
  /**
   * Carry a failing visual into the refinement below, so feedback is attached
   * to the plate it is about (`source_asset_id`) rather than to the campaign at
   * large. This is the one thread between the two halves of the page.
   */
  onGiveFeedback: (assetId: string) => void;
}) {
  const canRun = capabilities.can('edit_campaign');

  if (view.results.length === 0) {
    return (
      <EmptyState
        title="No brand check has run"
        description={
          view.can_check
            ? 'The Brand Guardian checks the work against the brand’s own rules — claims, tone, palette, product and logo — before anything ships.'
            : (view.blocked_reason ?? 'There is nothing to check yet.')
        }
        action={
          view.can_check && canRun ? (
            <Button
              variant="primary"
              size="lg"
              disabled={busy || pending}
              onClick={() => onCheck()}
            >
              {pending ? 'Checking…' : 'Run the brand check'}
            </Button>
          ) : undefined
        }
      />
    );
  }

  const remaining = view.unchecked_asset_ids;

  return (
    <div className="space-y-lg">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <p className="max-w-content text-body text-muted">
          Each visual is checked against what this brand allows. The checks are advice; whether
          the work ships is a human decision.
        </p>
        {/*
          One control, never two. When some visuals have never been checked that
          is the useful action and it is scoped to exactly those; otherwise the
          only thing left to do is run the whole set again. Two buttons here
          would be two next actions for one question.
        */}
        {view.can_check && canRun ? (
          remaining.length > 0 ? (
            <Button
              variant="primary"
              disabled={busy || pending}
              onClick={() => onCheck(remaining)}
            >
              {pending
                ? 'Checking…'
                : `Check the remaining ${remaining.length === 1 ? 'visual' : `${remaining.length} visuals`}`}
            </Button>
          ) : (
            <Button variant="secondary" disabled={busy || pending} onClick={() => onCheck()}>
              {pending ? 'Checking…' : 'Check every visual again'}
            </Button>
          )
        ) : null}
      </div>

      <ol className="space-y-5">
        {view.results.map((result, i) => (
          <GuardianResult
            key={result.id}
            result={result}
            index={i}
            canRetry={canRun}
            busy={busy}
            onRetry={() => onRetry(result.id)}
            onGiveFeedback={() => onGiveFeedback(result.generated_asset_id)}
          />
        ))}
      </ol>
    </div>
  );
}

function GuardianResult({
  result,
  index,
  canRetry,
  busy,
  onRetry,
  onGiveFeedback,
}: {
  result: GuardianResultView;
  index: number;
  canRetry: boolean;
  busy: boolean;
  onRetry: () => void;
  onGiveFeedback: () => void;
}) {
  const verdict = verdictMeaning(result.verdict);
  const checks = orderChecks(result.checks);
  const tally = checkTally(result.checks);
  const asset = result.asset;
  /**
   * A check still in flight is not a failed check. The previous board treated
   * every non-COMPLETED row as an error, which reads as "the brand check broke"
   * for the ninety seconds it is legitimately running.
   */
  const running = result.status === 'PENDING' || result.status === 'RUNNING';

  return (
    <Reveal as="li" index={index}>
      <Card padding={false} className="overflow-hidden">
        <div className="grid gap-0 lg:grid-cols-[minmax(0,20rem)_minmax(0,1fr)]">
          <div className="bg-line/30">
            {asset ? (
              <Plate
                src={mediaUrl(asset.url)}
                alt={`Visual being brand-checked, from ${providerLabel(asset.provider)}`}
                ratio={aspectRatio(asset)}
              />
            ) : (
              <PlateAbsent label="Visual unavailable" />
            )}
          </div>

          <div className="min-w-0 p-5 sm:p-6">
            {running ? (
              <div aria-live="polite">
                <p className="text-label uppercase text-muted">Brand check</p>
                <p className="mt-1 text-h3">Checking…</p>
                <p className="mt-2 text-small text-muted">
                  Reading this visual against the brand’s claims, tone, palette, product and
                  logo rules.
                </p>
              </div>
            ) : result.status !== 'COMPLETED' ? (
              <div role="alert">
                <p className="text-label uppercase text-muted">Brand check</p>
                {/* An outage must never read as brand approval. */}
                <p className="mt-1 text-h3 text-danger">Not checked</p>
                <p className="mt-2 text-small text-danger">
                  {result.error_message ?? 'The brand check did not finish.'}
                </p>
                {result.error_code ? (
                  <p className="mt-1 font-mono text-caption text-muted">{result.error_code}</p>
                ) : null}
                {canRetry && result.can_retry ? (
                  <Button variant="secondary" size="sm" className="mt-3" disabled={busy} onClick={onRetry}>
                    Run it again
                  </Button>
                ) : null}
              </div>
            ) : (
              <>
                {/*
                  The verdict, said once.

                  It used to be both a heading and a badge on the same card,
                  which reads as two verdicts that happen to agree. The word
                  carries the state on its own, so a greyscale reader loses
                  nothing when the colour goes.
                */}
                <p className="text-label uppercase text-muted">Brand check</p>
                {verdict ? (
                  <>
                    <p className={cx('mt-1 text-h3', VERDICT_INK[verdict.tone])}>
                      {verdict.label}
                    </p>
                    {/*
                      One supporting sentence, never two saying the same thing.

                      The backend's `summary` is about this particular visual
                      and is the better sentence when it says something — but
                      for a clean pass it is literally "Within the brand's
                      rules.", which is the verdict label again. Printing both
                      put the verdict on the card three times.
                    */}
                    <p className="mt-1 text-small text-muted">
                      {restates(result.summary, verdict.label) ? verdict.detail : result.summary}
                    </p>
                  </>
                ) : result.summary ? (
                  <p className="mt-1 text-small text-muted">{result.summary}</p>
                ) : null}

                {/* Counted, never estimated — and it is how the verdict is
                    shown to follow from the checks rather than to replace
                    them. */}
                <p className="mt-3 text-label uppercase text-muted">
                  {tally.passed} passed · {tally.warned} to look at · {tally.failed} failed
                  {tally.notApplicable > 0 ? ` · ${tally.notApplicable} not applicable` : ''}
                  {tally.deterministic > 0 ? ` · ${tally.deterministic} decided by code` : ''}
                </p>

                <ul className="mt-5 divide-y divide-line border-t border-line">
                  {checks.map((check) => {
                    const meaning = checkMeaning(check.status);
                    const why = whyItMatters(check.check);
                    return (
                      <li key={check.check} className="py-4">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <p className="text-body font-medium">{check.label}</p>
                          <div className="flex items-center gap-2">
                            {/* Colour is never the only signal. */}
                            <StatusBadge tone={meaning.tone}>{meaning.label}</StatusBadge>
                            {check.severity ? (
                              <span className="text-label uppercase text-muted">
                                {check.severity}
                              </span>
                            ) : null}
                          </div>
                        </div>

                        {/* What was found — the check's own words. */}
                        <p className="mt-1.5 text-small text-muted">{check.detail}</p>

                        {check.suggested_fix ? (
                          <p className="mt-1.5 text-small">
                            <span className="text-label uppercase text-muted">What to do </span>
                            {check.suggested_fix}
                          </p>
                        ) : null}

                        {why ? (
                          <p className="mt-1.5 text-caption text-muted">
                            {/* Attributed to us, because it is ours: the
                                backend has no "why it matters" field. */}
                            <span className="text-label uppercase">Campaign OS </span>
                            {why}
                          </p>
                        ) : null}

                        <p className="mt-1.5 text-label uppercase text-muted">
                          {check.deterministic
                            ? 'Decided by code'
                            : 'Judged by a model — a second opinion, not a fact'}
                        </p>
                      </li>
                    );
                  })}
                </ul>

                {result.critical_issues.length > 0 ? (
                  <div role="alert" className="mt-5 border-t border-line pt-4">
                    <p className="text-label uppercase text-danger">Must be resolved</p>
                    <ul className="mt-2 space-y-1">
                      {result.critical_issues.map((issue) => (
                        <li key={issue} className="text-small">
                          {issue}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}

                <div className="mt-5 border-t border-line pt-4">
                  <p className="text-caption text-muted">
                    The Brand Guardian advises. Whether this work ships is a person’s decision.
                  </p>
                  {/*
                    The route from a finding to a fix. Offered only where there
                    is something to fix, and it fills in the refinement below
                    rather than acting on its own — the plan is still read
                    before anything runs.
                  */}
                  {verdict && result.verdict !== 'PASS' ? (
                    <Button variant="secondary" size="sm" className="mt-3" onClick={onGiveFeedback}>
                      Refine this visual
                    </Button>
                  ) : null}
                </div>

                {/* Provenance: which guardian, judging which version. */}
                <p className="mt-4 text-caption text-muted">
                  Guardian {result.guardian_version}
                  {result.guardian_model ? ` · ${result.guardian_model}` : ''} · judged against
                  creative plan v{result.specification_version}
                </p>
              </>
            )}
          </div>
        </div>
      </Card>
    </Reveal>
  );
}
