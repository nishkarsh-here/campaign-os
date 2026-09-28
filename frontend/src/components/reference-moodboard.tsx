'use client';

/**
 * INSPIRATION — a moodboard that says what it learned.
 *
 * A reference is not decoration and not a template. ADR-011 is the whole
 * design of this screen: *learn the style, never copy the design*. So every
 * card shows three things — the reference, the characteristics the system read
 * from it, and, explicitly, what it will refuse to reuse.
 *
 * `ReferenceAnalysis.not_transferable` exists precisely so that refusal can be
 * shown rather than promised. Putting it on screen beside the takeaways is the
 * difference between a product that claims to respect other people's work and
 * one that can be checked.
 *
 * ## Two of the brief's chips do not exist
 *
 * The redesign asked for seven characteristic chips: Composition, Lighting,
 * Colour mood, Framing, Texture, Depth, Visual density. Five map to real
 * fields. **Texture and Depth have no field in `ReferenceAnalysis`** — the
 * analysis never extracted them. They are absent here rather than filled with
 * something plausible, because a chip reading "Soft texture" that no model
 * produced is a fabricated observation about someone's artwork.
 */

import { Card, Reveal, StatusBadge, cx } from '@/components/ui';
import { mediaUrl, type CampaignReference, type ReferenceAnalysis } from '@/lib/api';

/**
 * A characteristic, in the reader's words.
 *
 * `read` returns null when the analysis holds nothing for it — and a chip that
 * would be null is not drawn. Half the fields on `ReferenceAnalysis` are
 * nullable, because a model that could not tell says so.
 */
const CHARACTERISTICS: {
  label: string;
  read: (a: ReferenceAnalysis) => string | null;
  hint: string;
}[] = [
  {
    label: 'Composition',
    read: (a) => a.composition,
    hint: 'How the frame is arranged.',
  },
  {
    label: 'Lighting',
    read: (a) => a.lighting,
    hint: 'The quality and direction of light.',
  },
  {
    label: 'Colour mood',
    read: (a) => a.color.temperature,
    hint: 'Whether the palette runs warm or cool.',
  },
  {
    label: 'Framing',
    read: (a) => a.layout.subject_placement ?? a.subject_treatment,
    hint: 'Where the subject sits, and how it is treated.',
  },
  {
    label: 'Visual density',
    read: (a) => a.visual_density,
    hint: 'How much is happening in the frame.',
  },
  {
    label: 'Hierarchy',
    read: (a) => a.layout.hierarchy,
    hint: 'What the eye is led to first.',
  },
  {
    label: 'Image and text',
    read: (a) => a.layout.image_text_balance,
    hint: 'How much of the frame the words occupy.',
  },
];

export function ReferenceCard({
  reference,
  index,
  onAccept,
  canEdit,
  busy,
}: {
  reference: CampaignReference;
  index: number;
  /** One-way: the API accepts a reference, it does not un-accept one. */
  onAccept?: () => void;
  canEdit: boolean;
  busy: boolean;
}) {
  const analysis = reference.analysis;

  return (
    <Reveal as="li" index={index}>
      <Card padding={false} className="h-full overflow-hidden">
        <div className="grid gap-0 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
          {/* ------------------------------------------------ the reference */}
          <div className="relative bg-line/30">
            {/* `object-contain` on a neutral field: a reference is someone
                else's work being studied, not a hero image to be cropped for
                our layout. */}
            <img
              // `mediaUrl`, not the bare path: the API returns a path, and a
              // relative `src` resolves against the *page* origin — the Next
              // server, which serves no bytes. This rendered as a broken image
              // beside a perfectly good analysis of it.
              src={mediaUrl(reference.url)}
              alt={
                reference.note
                  ? `Reference: ${reference.note}`
                  : (reference.filename ?? 'Uploaded reference')
              }
              className="h-56 w-full object-contain lg:h-full lg:min-h-[16rem]"
            />
            {reference.accepted ? (
              <span className="absolute left-3 top-3">
                <StatusBadge tone="positive">In the mix</StatusBadge>
              </span>
            ) : null}
          </div>

          {/* -------------------------------------------- what we read in it */}
          <div className="min-w-0 p-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <h3 className="truncate text-h3">
                  {reference.note || reference.filename || 'Reference'}
                </h3>
                {analysis?.summary ? (
                  <p className="mt-1.5 max-w-content text-small text-muted">
                    {analysis.summary}
                  </p>
                ) : null}
              </div>
              <ReferenceState reference={reference} />
            </div>

            {analysis ? (
              <>
                <Characteristics analysis={analysis} />
                <Palette analysis={analysis} />
                <Influence analysis={analysis} />
              </>
            ) : reference.status === 'FAILED' ? (
              <p role="alert" className="mt-4 text-small text-danger">
                {reference.error ?? 'This reference could not be read.'}
              </p>
            ) : (
              <p className="mt-4 text-small text-muted">
                Reading the style from this reference…
              </p>
            )}

            {/* Accepting is one-way — `POST /references/:id/accept` has no
                inverse — so an accepted reference offers no control to undo it
                rather than a button that would fail. */}
            {onAccept && analysis && !reference.accepted ? (
              <div className="mt-5 border-t border-line pt-4">
                {canEdit ? (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={onAccept}
                    className={cx(
                      'rounded-md border border-accent px-3 py-1.5 text-body text-accent',
                      'transition-colors duration-fast hover:bg-accent/10',
                      'disabled:cursor-not-allowed disabled:opacity-50',
                    )}
                  >
                    Use this style
                  </button>
                ) : (
                  <p className="text-caption text-muted">
                    Your role is read-only for references.
                  </p>
                )}
              </div>
            ) : null}
          </div>
        </div>
      </Card>
    </Reveal>
  );
}

/** The four real `ReferenceStatus` values, in the reader's words. */
function ReferenceState({ reference }: { reference: CampaignReference }) {
  switch (reference.status) {
    case 'FAILED':
      return <StatusBadge tone="negative">Could not read</StatusBadge>;
    case 'COMPLETED':
      // A completed analysis needs no badge — the characteristics below are
      // the evidence. Only the absence of one is worth flagging.
      return reference.analysis ? null : <StatusBadge tone="neutral">No style read</StatusBadge>;
    case 'ANALYZING':
      return <StatusBadge tone="active">Reading the style</StatusBadge>;
    case 'PENDING':
    default:
      return <StatusBadge tone="neutral">Queued</StatusBadge>;
  }
}

/** The characteristics that actually came back. Absent ones are not drawn. */
function Characteristics({ analysis }: { analysis: ReferenceAnalysis }) {
  const present = CHARACTERISTICS.map((c) => ({ ...c, value: c.read(analysis) })).filter(
    (c) => c.value,
  );
  if (present.length === 0) return null;
  return (
    <dl className="mt-5 grid gap-x-6 gap-y-3 sm:grid-cols-2">
      {present.map((c) => (
        <div key={c.label}>
          <dt className="text-label uppercase text-muted" title={c.hint}>
            {c.label}
          </dt>
          {/* `first-letter:uppercase` because these arrive as lowercase enum
              words; capitalising in CSS avoids mangling the stored value. */}
          <dd className="mt-0.5 text-small first-letter:uppercase">{c.value}</dd>
        </div>
      ))}
    </dl>
  );
}

function Palette({ analysis }: { analysis: ReferenceAnalysis }) {
  const swatches = analysis.color.dominant_palette;
  if (swatches.length === 0) return null;
  return (
    <div className="mt-5">
      <p className="text-label uppercase text-muted">Palette read from it</p>
      <ul className="mt-2 flex flex-wrap gap-2">
        {swatches.slice(0, 8).map((hex) => (
          <li key={hex} className="flex items-center gap-1.5">
            <span
              aria-hidden="true"
              className="h-5 w-5 rounded-sm border border-line"
              style={{ background: hex }}
            />
            {/* Named as well as shown — a swatch alone is unreadable to
                anyone who cannot see the colour. */}
            <span className="font-mono text-caption uppercase text-muted">{hex}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * What this reference gives the campaign, and what it does not.
 *
 * Both lists are real fields. Showing them together is the honest form of
 * "how this influences the campaign": a promise about what will be taken is
 * only meaningful beside the refusal about what will not.
 */
function Influence({ analysis }: { analysis: ReferenceAnalysis }) {
  const { style_takeaways: takeaways, not_transferable: refused } = analysis;
  if (takeaways.length === 0 && refused.length === 0) return null;
  return (
    <div className="mt-5 border-t border-line pt-4">
      <p className="text-label uppercase text-muted">How this influences the campaign</p>
      {takeaways.length > 0 ? (
        <ul className="mt-2 space-y-1.5">
          {takeaways.map((t) => (
            <li key={t} className="flex gap-2 text-small">
              <span aria-hidden="true" className="text-success">
                +
              </span>
              <span>{t}</span>
            </li>
          ))}
        </ul>
      ) : null}
      {refused.length > 0 ? (
        <>
          <p className="mt-4 text-label uppercase text-muted">
            Deliberately not reused
          </p>
          <ul className="mt-2 space-y-1.5">
            {refused.map((t) => (
              <li key={t} className="flex gap-2 text-small text-muted">
                <span aria-hidden="true" className="text-danger">
                  −
                </span>
                <span>{t}</span>
              </li>
            ))}
          </ul>
          <p className="mt-3 text-caption text-muted">
            Campaign OS learns the style and never copies the design.
          </p>
        </>
      ) : null}
    </div>
  );
}
