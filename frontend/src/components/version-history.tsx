'use client';

/**
 * VERSION HISTORY — the campaign's creative plan, as an editorial record.
 *
 * A timeline rather than a table, because the question a person brings here is
 * "why does the work look like this now?" and the answer is a sequence of
 * decisions, not a list of rows.
 *
 * ## What it will not say
 *
 * **Who.** `SpecificationRevisionRow` has no `requested_by` and the API
 * projects none, so an entry reads "Revision recorded" and never a name. This
 * is the surface where an invented author would do the most damage: it is the
 * one people would cite in an argument about what happened.
 *
 * **That a version passed.** A version's brand standing comes from checks
 * stamped with that version. One nobody checked says so; it never borrows the
 * previous version's verdict, which is exactly the mistake a revision loop
 * invites.
 *
 * The rail borrows the Meridian's vocabulary — a drawn line, a marker per
 * node, the current one filled — without being a second navigation: selecting
 * a version changes what this panel compares, not where you are.
 */

import { useState } from 'react';
import { Button, Card, Plate, PlateAbsent, StatusBadge, cx } from '@/components/ui';
import { mediaUrl, type GeneratedAssetView } from '@/lib/api';
import { aspectRatio, providerLabel } from '@/lib/generation';
import {
  compareVersions,
  representativeAsset,
  revisionStatusMeaning,
  versionBrandStatus,
  type VersionEntry,
} from '@/lib/refinement';

function when(iso: string | null): string | null {
  if (!iso) return null;
  const parsed = new Date(iso);
  return Number.isNaN(parsed.getTime()) ? null : parsed.toLocaleDateString();
}

// ------------------------------------------------------------- the timeline

export function VersionHistory({
  versions,
  selectedAssetId,
}: {
  versions: VersionEntry[];
  /** The plate a person chose, preferred when a version holds several. */
  selectedAssetId: string | null;
}) {
  // Newest first: the question is almost always about the most recent step.
  const ordered = [...versions].reverse();
  const [comparing, setComparing] = useState<number | null>(null);

  if (!versions.length) {
    return (
      <p className="text-body text-muted">
        No plan versions yet. The first is written when the creative plan is approved.
      </p>
    );
  }

  const pair = (() => {
    if (comparing === null) return null;
    const to = versions.find((v) => v.version === comparing);
    const from = versions.find((v) => v.version === comparing - 1);
    return to && from ? compareVersions(from, to) : null;
  })();

  return (
    <div className="space-y-6">
      <ol className="version-rail relative space-y-4 pl-8">
        {ordered.map((entry, i) => {
          const brand = versionBrandStatus(entry);
          const status = entry.revision ? revisionStatusMeaning(entry.revision.status) : null;
          const date = when(entry.createdAt);
          const comparable = versions.some((v) => v.version === entry.version - 1) && entry.revision;

          return (
            <li key={entry.version} className="arrive relative" style={{ animationDelay: `${i * 50}ms` }}>
              {/* The marker. Filled for the plan in force, hollow otherwise —
                  shape as well as colour, like the Meridian's. */}
              <span
                aria-hidden="true"
                className={cx(
                  'absolute -left-8 top-1.5 h-3 w-3 rounded-full border-2',
                  entry.current ? 'border-accent bg-accent' : 'border-line bg-surface',
                )}
              />
              <Card className={cx(entry.current && 'border-l-2 border-l-accent')}>
                <div className="flex flex-wrap items-baseline justify-between gap-3">
                  <h4 className="text-h3">
                    v{entry.version}
                    {entry.current ? (
                      <span className="ml-3 align-middle text-label uppercase text-accent">
                        Current plan
                      </span>
                    ) : null}
                  </h4>
                  {date ? <span className="text-caption text-muted">{date}</span> : null}
                </div>

                <p className="mt-1.5 text-body">
                  {entry.summary ??
                    (entry.revision
                      ? 'Revision recorded'
                      : entry.version === 1
                        ? 'Initial creative plan'
                        : // Not "initial": the timeline holds the versions
                          // rows actually stamp, so the earliest one shown is
                          // not necessarily the first one that existed.
                          'No revision recorded for this version')}
                </p>

                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <StatusBadge tone={brand.tone}>{brand.label}</StatusBadge>
                  {status ? <StatusBadge tone={status.tone}>{status.label}</StatusBadge> : null}
                  {entry.assets.length ? (
                    <span className="text-caption text-muted">
                      {entry.assets.length} visual{entry.assets.length === 1 ? '' : 's'}
                    </span>
                  ) : (
                    // Not a failure: a plan can be approved with nothing built
                    // from it yet, and that is the state right after a revision.
                    <span className="text-caption text-muted">Nothing generated from it</span>
                  )}
                </div>

                {entry.revision?.user_feedback ? (
                  <figure className="mt-4 border-l-2 border-line pl-3">
                    <blockquote className="text-small text-muted">
                      “{entry.revision.user_feedback}”
                    </blockquote>
                    {/* Never a name: the API projects no author. */}
                    <figcaption className="mt-1 text-label uppercase text-muted">
                      Revision recorded
                    </figcaption>
                  </figure>
                ) : null}

                {entry.assets.length ? (
                  <ul className="mt-4 flex flex-wrap gap-2">
                    {entry.assets.slice(0, 4).map((asset) => (
                      <li key={asset.id}>
                        <img
                          src={mediaUrl(asset.url)}
                          alt={`Visual from plan v${entry.version}, ${providerLabel(asset.provider)}`}
                          className="h-16 w-16 rounded border border-line object-cover"
                        />
                      </li>
                    ))}
                  </ul>
                ) : null}

                {comparable ? (
                  <Button
                    variant="secondary"
                    size="sm"
                    className="mt-4"
                    aria-pressed={comparing === entry.version}
                    onClick={() =>
                      setComparing((current) =>
                        current === entry.version ? null : entry.version,
                      )
                    }
                  >
                    {comparing === entry.version
                      ? 'Hide the comparison'
                      : `Compare v${entry.version - 1} with v${entry.version}`}
                  </Button>
                ) : null}
              </Card>
            </li>
          );
        })}
      </ol>

      {pair ? (
        <VersionComparison
          comparison={pair}
          selectedAssetId={selectedAssetId}
          onClose={() => setComparing(null)}
        />
      ) : null}
    </div>
  );
}

// ------------------------------------------------------------ the comparison

type Comparison = NonNullable<ReturnType<typeof compareVersions>>;

/**
 * Two versions, side by side above 768px and one at a time below it.
 *
 * A two-column image comparison at phone width is two unreadable columns, so
 * the small screen gets a toggle instead — `aria-pressed` on real buttons, so
 * the state is announced rather than implied by colour.
 */
export function VersionComparison({
  comparison,
  selectedAssetId,
  onClose,
}: {
  comparison: Comparison;
  selectedAssetId: string | null;
  onClose: () => void;
}) {
  const [side, setSide] = useState<'from' | 'to'>('to');
  const sides = [
    { key: 'from' as const, entry: comparison.from, brand: comparison.brand.from },
    { key: 'to' as const, entry: comparison.to, brand: comparison.brand.to },
  ];

  return (
    <Card className="arrive">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h4 className="text-h3">
          v{comparison.from.version} compared with v{comparison.to.version}
        </h4>
        <Button variant="ghost" size="sm" onClick={onClose}>
          Close
        </Button>
      </div>

      {/* Below 768px the two panes become one, chosen here. */}
      <div className="mt-4 flex gap-2 sm:hidden" role="group" aria-label="Which version to show">
        {sides.map((s) => (
          <Button
            key={s.key}
            variant={side === s.key ? 'primary' : 'secondary'}
            size="sm"
            aria-pressed={side === s.key}
            onClick={() => setSide(s.key)}
          >
            v{s.entry.version}
          </Button>
        ))}
      </div>

      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        {sides.map((s) => {
          const asset = representativeAsset(s.entry, selectedAssetId);
          return (
            <figure
              key={s.key}
              className={cx('m-0', side !== s.key && 'hidden sm:block')}
            >
              <div className="overflow-hidden rounded-md border border-line bg-line/20">
                {asset ? (
                  <Plate
                    src={mediaUrl(asset.url)}
                    alt={`Visual from creative plan v${s.entry.version}, ${providerLabel(asset.provider)}`}
                    ratio={aspectRatio(asset)}
                  />
                ) : (
                  // A version can legitimately have no visual: approving a
                  // revision writes a plan, not a picture.
                  <PlateAbsent label={`Nothing generated from v${s.entry.version}`} />
                )}
              </div>
              <figcaption className="mt-2 flex flex-wrap items-center gap-2">
                <span className="text-label uppercase text-muted">v{s.entry.version}</span>
                <StatusBadge tone={s.brand.tone}>{s.brand.label}</StatusBadge>
              </figcaption>
            </figure>
          );
        })}
      </div>

      <div className="mt-5 grid gap-5 border-t border-line pt-4 sm:grid-cols-2">
        <div>
          <p className="text-label uppercase text-warning">What changed</p>
          {comparison.changed.length ? (
            <ul className="mt-2 space-y-2">
              {comparison.changed.map((row) => (
                <li key={row.field}>
                  <p className="text-small font-medium">{row.label}</p>
                  <p className="text-caption text-muted">{row.reason}</p>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-caption text-muted">Nothing was changed.</p>
          )}
        </div>
        <div>
          <p className="text-label uppercase text-muted">What stayed</p>
          {comparison.stayed.length ? (
            <ul className="mt-2 flex flex-wrap gap-2">
              {comparison.stayed.map((row) => (
                <li
                  key={row.field}
                  className="rounded-full border border-line bg-line/20 px-3 py-1 text-caption"
                >
                  {row.label}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-caption text-muted">Nothing was recorded as kept.</p>
          )}
        </div>
      </div>

      {/* The brand line is only drawn where a check exists on both sides. A
          version nobody checked is not a version that failed. */}
      {comparison.brand.from.unchecked || comparison.brand.to.unchecked ? (
        <p className="mt-4 border-t border-line pt-3 text-caption text-muted">
          {comparison.brand.to.unchecked
            ? `v${comparison.to.version} has not been brand-checked, so there is nothing to compare against v${comparison.from.version}.`
            : `v${comparison.from.version} was never brand-checked, so only v${comparison.to.version}'s result is shown.`}
        </p>
      ) : null}
    </Card>
  );
}

/** The plate a comparison shows for one side, exported for the page's tests. */
export type { GeneratedAssetView };
