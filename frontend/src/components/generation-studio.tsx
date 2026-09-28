'use client';

/**
 * GENERATE — the creative studio.
 *
 * The approved plan becomes visuals. The screen is built around the images,
 * with everything technical folded away, because the question here is "is this
 * any good?" and not "what did the provider return".
 *
 * ## One slot per provider, and that is what it says
 *
 * Generation fans out over image providers. There is no direction identity on
 * `GenerationView` anywhere, so a slot is titled by its provider and never
 * "Direction 01". The mock provider is named as a demo generator rather than
 * dressed up as a model — the offline demo must behave like the real workflow
 * without ever claiming to be one.
 */

import { Button, Card, EmptyState, Plate, Reveal, StatusBadge, cx } from '@/components/ui';
import { mediaUrl, type GenerationView } from '@/lib/api';
import type { Capabilities } from '@/lib/capabilities';
import {
  aspectRatio,
  isOfflineProvider,
  providerLabel,
  slots,
  technicalFacts,
  type Slot,
} from '@/lib/generation';

export function GenerationStudio({
  view,
  capabilities,
  busy,
  onGenerate,
  onRetry,
}: {
  view: GenerationView;
  capabilities: Capabilities;
  busy: boolean;
  onGenerate: () => void;
  onRetry: (jobId: string) => void;
}) {
  const list = slots(view);
  const canGenerate = capabilities.can('edit_campaign');

  if (!view.can_generate && list.length === 0) {
    return (
      <EmptyState
        title="Not ready to generate"
        description={
          // The backend authors this sentence; it knows why.
          view.blocked_reason ?? 'The creative plan has to be approved before anything is made.'
        }
      />
    );
  }

  if (list.length === 0) {
    return (
      <EmptyState
        title="No visuals yet"
        description="The approved creative plan is turned into visuals here. Nothing has been generated for this campaign."
        action={
          canGenerate ? (
            <Button variant="primary" size="lg" disabled={busy} onClick={onGenerate}>
              {busy ? 'Starting…' : 'Generate campaign visuals'}
            </Button>
          ) : undefined
        }
      />
    );
  }

  return (
    <div className="space-y-lg">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          {/* The backend's own sentence: "2/3 providers succeeded — 1 failed."
              A partial failure is reported as a partial failure, and does not
              turn the whole screen into an error. */}
          <p className="text-body">{view.outcome}</p>
          {view.specification_version !== null ? (
            <p className="mt-1 text-label uppercase text-muted">
              From creative plan v{view.specification_version}
            </p>
          ) : null}
        </div>
        {canGenerate && view.can_generate ? (
          <Button variant="secondary" disabled={busy} onClick={onGenerate}>
            {busy ? 'Working…' : 'Generate again'}
          </Button>
        ) : null}
      </div>

      <ul className="grid gap-5 lg:grid-cols-2 xl:grid-cols-3">
        {list.map((slot, i) => (
          <GenerationSlot
            key={slot.job.id}
            slot={slot}
            index={i}
            canRetry={canGenerate}
            busy={busy}
            onRetry={() => onRetry(slot.job.id)}
          />
        ))}
      </ul>
    </div>
  );
}

function GenerationSlot({
  slot,
  index,
  canRetry,
  busy,
  onRetry,
}: {
  slot: Slot;
  index: number;
  canRetry: boolean;
  busy: boolean;
  onRetry: () => void;
}) {
  const { job, assets, meaning } = slot;
  const asset = assets[0];

  return (
    <Reveal as="li" index={index} className="h-full">
      <Card padding={false} className="flex h-full flex-col overflow-hidden">
        {/* --------------------------------------------------- the visual */}
        {asset ? (
          <Plate
            src={mediaUrl(asset.url)}
            alt={`Visual from ${providerLabel(asset.provider)}, ${asset.width} by ${asset.height} pixels`}
            ratio={aspectRatio(asset)}
          />
        ) : (
          <div
            className="flex items-center justify-center bg-line/20"
            style={{ aspectRatio: '4 / 5' }}
          >
            <p className={cx('text-label uppercase', meaning.live && 'animate-pulse')}>
              {/* The state, in the frame where the image will be. */}
              {meaning.label}
            </p>
          </div>
        )}

        {/* ---------------------------------------------------- the facts */}
        <div className="flex flex-1 flex-col p-5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-h3">{providerLabel(job.provider)}</h3>
            <StatusBadge tone={meaning.tone}>{meaning.label}</StatusBadge>
          </div>

          {isOfflineProvider(job.provider) ? (
            // Said plainly. "Is this real output?" is the first question
            // anyone watching a demo has, and guessing is worse than either
            // answer.
            <p className="mt-1.5 text-caption text-muted">
              Offline demo output. Nothing left this machine.
            </p>
          ) : null}

          {job.status === 'FAILED' ? (
            <div role="alert" className="mt-3">
              <p className="text-small text-danger">
                {/* The server's message, which is written for a person. No
                    stack traces reach this screen. */}
                {job.error_message ?? 'The provider could not produce a visual.'}
              </p>
              {canRetry && job.can_retry ? (
                <Button variant="secondary" size="sm" className="mt-3" disabled={busy} onClick={onRetry}>
                  Try this provider again
                </Button>
              ) : null}
            </div>
          ) : (
            <p className="mt-1.5 text-small text-muted">{meaning.detail}</p>
          )}

          <details className="group mt-auto pt-4">
            <summary className="cursor-pointer list-none text-label uppercase text-muted transition-colors duration-fast hover:text-ink">
              <span className="group-open:hidden">Generation details →</span>
              <span className="hidden group-open:inline">Hide details ↑</span>
            </summary>
            <dl className="mt-3 space-y-1.5 border-t border-line pt-3">
              {technicalFacts(slot).map((f) => (
                <div key={f.label} className="flex justify-between gap-4">
                  <dt className="text-caption text-muted">{f.label}</dt>
                  <dd className="truncate font-mono text-caption" title={f.value}>
                    {f.value}
                  </dd>
                </div>
              ))}
            </dl>
            {/* No request id, seed or provider latency rows: the API carries
                none of them, and an empty row implies one exists and was lost. */}
          </details>
        </div>
      </Card>
    </Reveal>
  );
}
