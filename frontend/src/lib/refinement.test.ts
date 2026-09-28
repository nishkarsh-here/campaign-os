/**
 * Reading the refinement stage.
 *
 * Two classes of assertion here. The ordinary kind — labels, states, plans —
 * and the ones that exist because this is an audit surface: that no version
 * claims an author, that no version inherits another's brand verdict, and that
 * a version appears only because a real row carries its number.
 */

import { describe, expect, it } from 'vitest';
import * as refinement from './refinement';
import {
  ACTION_MEANING,
  compareVersions,
  fieldLabel,
  localizationContext,
  protectedFields,
  refinementState,
  representativeAsset,
  revisionPlan,
  revisionStatusMeaning,
  versionBrandStatus,
  versionTimeline,
} from './refinement';
import type {
  CampaignSpecification,
  CreativeSpecification,
  EvaluationView,
  GeneratedAssetView,
  GenerationView,
  GuardianResultView,
  GuardianView,
  RevisionDeltaView,
  RevisionRecordView,
  RevisionView,
} from './api';

// ----------------------------------------------------------------- fixtures

function delta(over: Partial<RevisionDeltaView> = {}): RevisionDeltaView {
  return {
    iteration: 1,
    user_feedback: 'Make the setting feel local.',
    interpretation: 'Change environment; keep everything else.',
    keep: ['cta', 'concept', 'product_integration'],
    change: [
      {
        field: 'environment',
        label: 'Environment',
        action: 'CHANGE',
        reason: 'Addresses your note about the environment.',
        current_value: 'a fabrication floor',
        new_value: 'a recognisably local context',
      },
    ],
    add: [],
    remove: [],
    explicit_unlocks: [],
    rationale: 'Addresses your feedback and preserves the approved facts.',
    ...over,
  };
}

function record(over: Partial<RevisionRecordView> = {}): RevisionRecordView {
  return {
    id: 'r-1',
    iteration: 1,
    status: 'APPROVED',
    user_feedback: 'Make the setting feel local.',
    delta: delta(),
    changed_fields: ['environment'],
    from_version: 2,
    to_version: 3,
    source_asset_id: null,
    created_at: '2026-01-02T10:00:00Z',
    ...over,
  };
}

function revision(over: Partial<RevisionView> = {}): RevisionView {
  return {
    campaign_id: 'c-1',
    current: record(),
    history: [record()],
    diff: [],
    can_revise: true,
    blocked_reason: null,
    ...over,
  };
}

function asset(over: Partial<GeneratedAssetView> = {}): GeneratedAssetView {
  return {
    id: 'a-1',
    generation_job_id: 'j-1',
    provider: 'mock',
    model: 'mock-image-1',
    kind: 'VISUAL_PLATE' as GeneratedAssetView['kind'],
    width: 1024,
    height: 1024,
    mime_type: 'image/png',
    url: '/v1/campaigns/c-1/assets/a-1/content?token=signed',
    specification_version: 3,
    created_at: '2026-01-02T10:05:00Z',
    ...over,
  };
}

function guardianResult(over: Partial<GuardianResultView> = {}): GuardianResultView {
  return {
    id: 'g-1',
    generated_asset_id: 'a-1',
    status: 'COMPLETED',
    guardian_version: 'v1',
    guardian_model: 'mock',
    specification_version: 3,
    verdict: 'PASS',
    checks: [],
    critical_issues: [],
    warnings: [],
    summary: '',
    error_message: null,
    error_code: null,
    can_retry: false,
    evaluated_at: null,
    asset: asset(),
    ...over,
  };
}

function guardian(over: Partial<GuardianView> = {}): GuardianView {
  return {
    campaign_id: 'c-1',
    guardian_version: 'v1',
    results: [guardianResult()],
    in_flight: 0,
    unchecked_asset_ids: [],
    can_check: true,
    blocked_reason: null,
    ...over,
  };
}

function generation(over: Partial<GenerationView> = {}): GenerationView {
  return {
    campaign_id: 'c-1',
    batch_id: 'b-1',
    canonical_prompt: null,
    prompts: [],
    jobs: [],
    assets: [asset()],
    outcome: 'All 1 provider succeeded.',
    complete: true,
    specification_version: 3,
    can_generate: true,
    blocked_reason: null,
    ...over,
  };
}

const NO_EVALUATION: EvaluationView | null = null;

// ------------------------------------------------------------------- labels

describe('fieldLabel', () => {
  it('replaces the labels that leak vocabulary', () => {
    // The server's own label is `name.replace('_',' ').capitalize()`, so this
    // field arrives as "Cta", which is not a word.
    expect(fieldLabel('cta', 'Cta')).toBe('Call to action');
    expect(fieldLabel('environment', 'Environment')).toBe('Setting');
  });

  it('falls through to the server label for anything it does not know', () => {
    expect(fieldLabel('a_field_added_later', 'A field added later')).toBe('A field added later');
  });

  it('falls through to the field name when there is no server label', () => {
    expect(fieldLabel('a_field_added_later')).toBe('A field added later');
  });
});

// --------------------------------------------------------------- the plan

describe('revisionPlan', () => {
  it('reads every action group with the planner’s own reasons', () => {
    const plan = revisionPlan(delta());
    expect(plan.change).toHaveLength(1);
    expect(plan.change[0]!.label).toBe('Setting');
    expect(plan.change[0]!.reason).toBe('Addresses your note about the environment.');
    expect(plan.change[0]!.before).toBe('a fabrication floor');
    expect(plan.change[0]!.after).toBe('a recognisably local context');
  });

  it('labels the kept fields rather than printing snake_case at a reader', () => {
    expect(revisionPlan(delta()).keep.map((k) => k.label)).toEqual([
      'Call to action',
      'The idea',
      'How the product appears',
    ]);
  });

  it('reports a plan that touches nothing as empty, which is a real outcome', () => {
    const plan = revisionPlan(delta({ change: [], add: [], remove: [] }));
    expect(plan.empty).toBe(true);
    expect(plan.keep.length).toBeGreaterThan(0);
  });

  it('carries the explicit unlocks, which a reader must not miss', () => {
    const plan = revisionPlan(delta({ explicit_unlocks: ['cta'] }));
    expect(plan.unlocks).toEqual([{ field: 'cta', label: 'Call to action' }]);
  });

  it('names every action in words, so colour is never the only signal', () => {
    for (const action of ['KEEP', 'CHANGE', 'ADD', 'REMOVE'] as const) {
      expect(ACTION_MEANING[action].label).toBeTruthy();
    }
  });
});

// ------------------------------------------------------------- where we are

describe('revisionStatusMeaning', () => {
  it('says that an applied revision is still waiting on a person', () => {
    // "Applied" reads as finished and is not: the version exists, nobody has
    // accepted it.
    expect(revisionStatusMeaning('APPLIED').awaitsHuman).toBe(true);
    expect(revisionStatusMeaning('PROPOSED').awaitsHuman).toBe(true);
    expect(revisionStatusMeaning('APPROVED').awaitsHuman).toBe(false);
    expect(revisionStatusMeaning('REJECTED').awaitsHuman).toBe(false);
  });

  it('never shows a raw enum', () => {
    for (const status of ['PROPOSED', 'APPLIED', 'APPROVED', 'REJECTED'] as const) {
      expect(revisionStatusMeaning(status).label).not.toMatch(/_|[A-Z]{3,}/);
    }
  });
});

describe('refinementState', () => {
  it('invites feedback when no round is open', () => {
    const state = refinementState(revision({ current: null, history: [] }));
    expect(state.step).toBe('feedback');
    expect(state.canStartRound).toBe(true);
  });

  it('holds the round open while a plan awaits approval', () => {
    const state = refinementState(revision({ current: record({ status: 'PROPOSED' }) }));
    expect(state.step).toBe('plan');
    expect(state.canStartRound).toBe(false);
  });

  it('never implies an approved revision produced a visual or passed the guardian', () => {
    // The two things a reader is most likely to assume and most likely to be
    // wrong about.
    const state = refinementState(revision({ current: record({ status: 'APPROVED' }) }));
    expect(state.step).toBe('regenerate');
    expect(state.next).toMatch(/nothing has been generated/i);
    expect(state.next).toMatch(/not been brand-checked/i);
  });

  it('reports the backend’s own reason when refinement is closed', () => {
    const state = refinementState(
      revision({ current: null, history: [], can_revise: false, blocked_reason: 'Generate first.' }),
    );
    expect(state.step).toBe('blocked');
    expect(state.headline).toBe('Generate first.');
  });
});

// --------------------------------------------------------------- protection

describe('protectedFields', () => {
  it('shows the standing locks the specification actually carries', () => {
    const spec = { locked_fields: ['cta', 'product_integration'] } as CreativeSpecification;
    const groups = protectedFields(delta(), spec);
    expect(groups[0]!.title).toBe('Locked by Campaign OS');
    expect(groups[0]!.items.map((i) => i.label)).toEqual([
      'Call to action',
      'How the product appears',
    ]);
  });

  it('shows nothing rather than a reassuring fiction when there are no locks', () => {
    // `locked_fields` is populated by `apply_revision`, so a plan that has
    // never been revised carries none.
    const spec = { locked_fields: [] } as unknown as CreativeSpecification;
    const groups = protectedFields(null, spec);
    expect(groups).toEqual([]);
  });

  it('states a locked field once, not also as kept', () => {
    // `delta.keep` normally repeats the locked fields. Listing both reads as
    // two protections where there is one.
    const spec = { locked_fields: ['cta'] } as CreativeSpecification;
    const groups = protectedFields(delta({ keep: ['cta', 'concept'] }), spec);
    const locked = groups.find((g) => g.title === 'Locked by Campaign OS')!;
    const kept = groups.find((g) => g.title === 'Kept exactly as approved')!;
    expect(locked.items.map((i) => i.field)).toEqual(['cta']);
    expect(kept.items.map((i) => i.field)).toEqual(['concept']);
  });

  it('moves an unlocked field out of the protected groups and names it', () => {
    const spec = { locked_fields: ['cta'] } as CreativeSpecification;
    const groups = protectedFields(delta({ explicit_unlocks: ['cta'] }), spec);
    expect(groups.find((g) => g.title === 'Locked by Campaign OS')).toBeUndefined();
    const unlocked = groups.find((g) => g.title === 'Unlocked because you asked');
    expect(unlocked?.items.map((i) => i.label)).toEqual(['Call to action']);
    // And it is not simultaneously claimed as kept.
    const kept = groups.find((g) => g.title === 'Kept exactly as approved');
    expect(kept?.items.map((i) => i.field)).not.toContain('cta');
  });
});

// ------------------------------------------------------------ localization

describe('localizationContext', () => {
  const spec = {
    region: 'Mumbai, Maharashtra',
    language: 'English',
    audience: 'Architects',
    timing_occasion: null,
    required_elements: ['the FS-9 panel'],
    avoid_restrictions: ['monsoon imagery'],
  } as unknown as CampaignSpecification;

  it('reads the market context the brief actually records', () => {
    const context = localizationContext(spec);
    expect(context.rows.map((r) => r.label)).toEqual(['Market', 'Language', 'Audience']);
    expect(context.required).toEqual(['the FS-9 panel']);
    expect(context.known).toBe(true);
  });

  it('reads an ISO language code as a language', () => {
    // A live brief stores "en". That is not a language to a reader.
    const context = localizationContext({ ...spec, language: 'en' } as CampaignSpecification);
    expect(context.rows.find((r) => r.label === 'Language')?.value).toBe('English');
  });

  it('omits an absent value rather than filling one in', () => {
    const context = localizationContext({ ...spec, region: null } as CampaignSpecification);
    expect(context.rows.map((r) => r.label)).not.toContain('Market');
  });

  it('reports that nothing is known when the brief records nothing', () => {
    expect(localizationContext(null).known).toBe(false);
  });
});

// ---------------------------------------------------------------- versions

describe('versionTimeline', () => {
  it('builds a version only from rows that carry its number', () => {
    const timeline = versionTimeline(revision(), guardian(), generation(), NO_EVALUATION);
    expect(timeline.map((v) => v.version)).toEqual([2, 3]);
  });

  it('attaches each plate to the version it was built from', () => {
    const timeline = versionTimeline(
      revision(),
      guardian({
        results: [
          guardianResult({ id: 'g-2', specification_version: 2, asset: asset({ id: 'old', specification_version: 2 }) }),
          guardianResult(),
        ],
      }),
      generation(),
      NO_EVALUATION,
    );
    expect(timeline.find((v) => v.version === 2)!.assets.map((a) => a.id)).toEqual(['old']);
    expect(timeline.find((v) => v.version === 3)!.assets.map((a) => a.id)).toEqual(['a-1']);
  });

  it('marks the plan generation is working from as current', () => {
    const timeline = versionTimeline(revision(), guardian(), generation(), NO_EVALUATION);
    expect(timeline.find((v) => v.current)!.version).toBe(3);
  });

  it('summarises a version by what it changed, not by a count', () => {
    const timeline = versionTimeline(revision(), guardian(), generation(), NO_EVALUATION);
    expect(timeline.find((v) => v.version === 3)!.summary).toBe('Setting');
  });

  it('gives the first version no revision and no summary', () => {
    const first = versionTimeline(revision(), guardian(), generation(), NO_EVALUATION).find(
      (v) => v.version === 2,
    )!;
    expect(first.revision).toBeNull();
    expect(first.summary).toBeNull();
  });

  it('never claims who made a change', () => {
    // `SpecificationRevisionRow` has no `requested_by` and the API projects
    // none. An audit surface is the worst place to invent an author.
    const timeline = versionTimeline(revision(), guardian(), generation(), NO_EVALUATION);
    expect(JSON.stringify(timeline)).not.toMatch(/requested_by|author|by [A-Z][a-z]+ [A-Z]/);
  });

  it('tolerates a campaign with nothing in it', () => {
    expect(versionTimeline(null, null, null, null)).toEqual([]);
  });

  it('includes a version that only plates carry, with no revision row', () => {
    const timeline = versionTimeline(
      null,
      null,
      generation({ assets: [asset({ specification_version: 1 })], specification_version: 1 }),
      NO_EVALUATION,
    );
    expect(timeline.map((v) => v.version)).toEqual([1]);
    expect(timeline[0]!.assets).toHaveLength(1);
  });
});

describe('versionBrandStatus', () => {
  const timeline = () => versionTimeline(revision(), guardian(), generation(), NO_EVALUATION);

  it('reports a version nobody checked as unchecked, never as a pass', () => {
    const v2 = timeline().find((v) => v.version === 2)!;
    expect(v2.verdicts).toEqual([]);
    const status = versionBrandStatus(v2);
    expect(status.unchecked).toBe(true);
    expect(status.label).toBe('Not brand-checked');
    expect(status.label).not.toMatch(/pass|within/i);
  });

  it('reads a version’s own verdict', () => {
    const v3 = timeline().find((v) => v.version === 3)!;
    expect(versionBrandStatus(v3).label).toBe('Within the brand’s rules');
  });

  it('reports the worst verdict when a version has several', () => {
    const entry = {
      version: 3,
      revision: null,
      summary: null,
      assets: [],
      verdicts: ['PASS', 'REJECT', 'PASS'] as const,
      current: true,
      createdAt: null,
    };
    expect(versionBrandStatus({ ...entry, verdicts: [...entry.verdicts] }).label).toBe(
      'Cannot ship',
    );
  });
});

describe('compareVersions', () => {
  const timeline = () => versionTimeline(revision(), guardian(), generation(), NO_EVALUATION);

  it('compares two versions through the revision that joins them', () => {
    const [from, to] = timeline();
    const comparison = compareVersions(from!, to!)!;
    expect(comparison.changed.map((c) => c.label)).toEqual(['Setting']);
    expect(comparison.stayed.map((s) => s.label)).toContain('Call to action');
  });

  it('carries each side’s own brand standing, never one inherited', () => {
    const [from, to] = timeline();
    const comparison = compareVersions(from!, to!)!;
    expect(comparison.brand.from.unchecked).toBe(true);
    expect(comparison.brand.to.unchecked).toBe(false);
  });

  it('refuses a pair no revision record joins', () => {
    // v1 to v3 would need a diff nobody computed.
    const stray = {
      version: 1,
      revision: null,
      summary: null,
      assets: [],
      verdicts: [],
      current: false,
      createdAt: null,
    };
    const [, to] = timeline();
    expect(compareVersions(stray, to!)).toBeNull();
  });
});

describe('representativeAsset', () => {
  const entry = () => versionTimeline(revision(), guardian(), generation(), NO_EVALUATION)[1]!;

  it('prefers the asset a person selected', () => {
    expect(representativeAsset(entry(), 'a-1')?.id).toBe('a-1');
  });

  it('falls back to the version’s first plate', () => {
    expect(representativeAsset(entry(), 'not-in-this-version')?.id).toBe('a-1');
  });

  it('returns null for a version with no plate, rather than borrowing one', () => {
    const empty = { ...entry(), assets: [] };
    expect(representativeAsset(empty, 'a-1')).toBeNull();
  });
});

describe('what this module refuses to provide', () => {
  it('exposes no helper that could name a person', () => {
    const surface = Object.keys(refinement).join(' ').toLowerCase();
    expect(surface).not.toMatch(/author|requestedby|requested_by|\buser\b/);
  });
});
