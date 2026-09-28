// @vitest-environment jsdom

/**
 * The refinement workspace and the version record.
 *
 * Behaviour and governance. The governance half matters most here: this is the
 * surface people would cite in an argument about what happened to a campaign,
 * so it must never name an author it does not have, never carry a brand
 * verdict from one version to another, and never show a version that no row
 * actually stamps.
 */

import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
import {
  CurrentCreative,
  GuardianLoop,
  LocalizationPanel,
  ProtectedPanel,
  RevisedPlanCard,
  RevisionPlanCard,
  RevisionRequest,
} from './refinement-workspace';
import { VersionHistory } from './version-history';
import { capabilitiesFor } from '@/lib/capabilities';
import {
  localizationContext,
  protectedFields,
  refinementState,
  revisionPlan,
  versionBrandStatus,
  versionTimeline,
} from '@/lib/refinement';
import type {
  CampaignSpecification,
  CreativeSpecification,
  GeneratedAssetView,
  GenerationView,
  GuardianResultView,
  GuardianView,
  RevisionDeltaView,
  RevisionRecordView,
  RevisionView,
} from '@/lib/api';

const admin = capabilitiesFor('admin');
const designer = capabilitiesFor('designer');
const viewer = capabilitiesFor('viewer');
const noop = () => undefined;

// ----------------------------------------------------------------- fixtures

function asset(over: Partial<GeneratedAssetView> = {}): GeneratedAssetView {
  return {
    id: 'a-3',
    generation_job_id: 'j-1',
    provider: 'mock',
    model: 'mock-image-1',
    kind: 'VISUAL_PLATE' as GeneratedAssetView['kind'],
    width: 1024,
    height: 1024,
    mime_type: 'image/png',
    url: '/v1/campaigns/c-1/assets/a-3/content?token=signed-token',
    specification_version: 3,
    created_at: '2026-01-02T10:05:00Z',
    ...over,
  };
}

function delta(over: Partial<RevisionDeltaView> = {}): RevisionDeltaView {
  return {
    iteration: 1,
    user_feedback: 'Make the setting feel local.',
    interpretation: 'Change environment; keep everything else.',
    keep: ['cta', 'product_integration'],
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
    rationale: 'Preserves the approved product, message and call to action.',
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
    diff: [
      {
        field: 'environment',
        label: 'Environment',
        before: 'a fabrication floor',
        after: 'a recognisably local context',
      },
    ],
    can_revise: true,
    blocked_reason: null,
    ...over,
  };
}

function guardianResult(over: Partial<GuardianResultView> = {}): GuardianResultView {
  return {
    id: 'g-1',
    generated_asset_id: 'a-3',
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
    outcome: '',
    complete: true,
    specification_version: 3,
    can_generate: true,
    blocked_reason: null,
    ...over,
  };
}

const campaignSpec = {
  region: 'Mumbai, Maharashtra',
  language: 'English',
  audience: 'Architects and facade consultants',
  timing_occasion: null,
  required_elements: ['the FS-9 panel'],
  avoid_restrictions: ['monsoon imagery'],
  channels: ['linkedin'],
} as unknown as CampaignSpecification;

const timeline = () => versionTimeline(revision(), guardian(), generation(), null);

// ------------------------------------------------------- the current creative

describe('CurrentCreative', () => {
  const facts = (over = {}) => ({
    campaign: 'FS-9 Facade Launch',
    brand: 'Northline Facades',
    market: 'Mumbai, Maharashtra',
    channels: ['linkedin'],
    version: 3,
    brandStatus: versionBrandStatus(timeline()[1]!),
    ...over,
  });

  it('shows the work, through a signed media URL', () => {
    render(<CurrentCreative asset={asset()} facts={facts()} supersededBy={null} />);
    const img = screen.getByRole('img');
    expect(img.getAttribute('src')).toContain('token=signed-token');
    expect(img.getAttribute('alt')).toMatch(/current creative, from Demo generator/);
  });

  it('places the creative with the facts the brief actually carries', () => {
    render(<CurrentCreative asset={asset()} facts={facts()} supersededBy={null} />);
    expect(screen.getByText('Northline Facades')).toBeTruthy();
    expect(screen.getByText('Mumbai, Maharashtra')).toBeTruthy();
    expect(screen.getByText('Creative plan v3')).toBeTruthy();
    expect(screen.getByText('Within the brand’s rules')).toBeTruthy();
  });

  it('says a visual could not be loaded rather than captioning a dark box', () => {
    render(<CurrentCreative asset={asset()} facts={facts()} supersededBy={null} />);
    fireEvent.error(screen.getByRole('img'));
    expect(screen.getByText('Visual could not be loaded')).toBeTruthy();
  });

  it('says there is no creative rather than drawing an empty frame', () => {
    render(<CurrentCreative asset={null} facts={facts({ version: null })} supersededBy={null} />);
    expect(screen.getByText('No creative selected yet')).toBeTruthy();
    expect(screen.getByText('Not recorded')).toBeTruthy();
    expect(screen.queryByRole('img')).toBeNull();
  });

  it('warns when the visual predates the current plan', () => {
    // The live benchmark is in exactly this state.
    render(<CurrentCreative asset={asset({ specification_version: 2 })} facts={facts({ version: 2 })} supersededBy={3} />);
    expect(screen.getByText(/built from an earlier plan/i)).toBeTruthy();
    expect(screen.getByText(/current plan is v3/)).toBeTruthy();
  });
});

// ---------------------------------------------------------- asking for change

describe('RevisionRequest', () => {
  const props = (over = {}) => ({
    busy: false,
    capabilities: admin,
    attachedAsset: null,
    onDetach: noop,
    onSubmit: noop,
    ...over,
  });

  it('sends the note the person actually wrote', () => {
    const onSubmit = vi.fn();
    render(<RevisionRequest {...props({ onSubmit })} />);
    fireEvent.change(screen.getByLabelText('What would you like to change?'), {
      target: { value: 'Cool the grade.' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Plan the revision' }));
    expect(onSubmit).toHaveBeenCalledWith('Cool the grade.');
  });

  it('will not send an empty note', () => {
    render(<RevisionRequest {...props()} />);
    expect(
      screen.getByRole('button', { name: 'Plan the revision' }).hasAttribute('disabled'),
    ).toBe(true);
  });

  it('writes a prompt into the note rather than inventing a second field', () => {
    // `POST /revision` takes one string. The prompts compose that string.
    render(<RevisionRequest {...props()} />);
    fireEvent.click(screen.getByRole('button', { name: 'Lighting' }));
    const box = screen.getByLabelText('What would you like to change?') as HTMLTextAreaElement;
    expect(box.value).toContain('Change the lighting');
  });

  it('says which visual the feedback is attached to, and lets it go', () => {
    const onDetach = vi.fn();
    render(<RevisionRequest {...props({ attachedAsset: asset(), onDetach })} />);
    expect(screen.getByText('Feedback attached to this visual')).toBeTruthy();
    expect(screen.getAllByRole('img')[0]!.getAttribute('src')).toContain('token=');
    fireEvent.click(screen.getByRole('button', { name: 'Detach' }));
    expect(onDetach).toHaveBeenCalled();
  });

  it('says nothing is generated by this step', () => {
    render(<RevisionRequest {...props()} />);
    expect(screen.getByText(/Nothing is generated by this step/)).toBeTruthy();
  });

  it('offers nothing to someone who cannot request a revision', () => {
    render(<RevisionRequest {...props({ capabilities: viewer })} />);
    expect(screen.getByText(/needs edit rights/i)).toBeTruthy();
    expect(screen.queryByRole('textbox')).toBeNull();
  });
});

// ------------------------------------------------------------ the plan

describe('RevisionPlanCard', () => {
  const props = (over = {}) => ({
    plan: revisionPlan(delta()),
    iteration: 1,
    fromVersion: 2,
    busy: false,
    capabilities: admin,
    onApprove: noop,
    onEdit: noop,
    onDiscard: noop,
    ...over,
  });

  it('shows each planned change with the planner’s own reason', () => {
    render(<RevisionPlanCard {...props()} />);
    expect(screen.getByText('Changing')).toBeTruthy();
    expect(screen.getByText('Setting')).toBeTruthy();
    expect(screen.getByText('Addresses your note about the environment.')).toBeTruthy();
    expect(screen.getByText('a fabrication floor')).toBeTruthy();
    expect(screen.getByText('a recognisably local context')).toBeTruthy();
  });

  it('names every action in words, never colour alone', () => {
    const plan = revisionPlan(
      delta({
        add: [
          { field: 'regional_cues', label: 'Regional cues', action: 'ADD', reason: 'r', current_value: null, new_value: 'a local cue' },
        ],
        remove: [
          { field: 'people_guidance', label: 'People guidance', action: 'REMOVE', reason: 'r2', current_value: 'crowd', new_value: null },
        ],
      }),
    );
    render(<RevisionPlanCard {...props({ plan })} />);
    for (const word of ['Changing', 'Adding', 'Removing']) {
      expect(screen.getByText(word), word).toBeTruthy();
    }
  });

  it('reports a plan that would change nothing, which is a real answer', () => {
    const plan = revisionPlan(delta({ change: [], add: [], remove: [] }));
    render(<RevisionPlanCard {...props({ plan })} />);
    expect(screen.getByText('Nothing would change')).toBeTruthy();
    // And there is nothing to edit.
    expect(screen.queryByRole('button', { name: 'Edit the plan' })).toBeNull();
  });

  it('creates the revised version on approval', () => {
    const onApprove = vi.fn();
    render(<RevisionPlanCard {...props({ onApprove })} />);
    fireEvent.click(screen.getByRole('button', { name: 'Create revised version' }));
    expect(onApprove).toHaveBeenCalled();
  });

  it('edits a field value and carries the planner’s reason forward', () => {
    const onEdit = vi.fn();
    render(<RevisionPlanCard {...props({ onEdit })} />);
    fireEvent.click(screen.getByRole('button', { name: 'Edit the plan' }));
    fireEvent.change(screen.getByLabelText('Setting — proposed value'), {
      target: { value: 'a Mumbai fabrication yard' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save the plan' }));
    expect(onEdit).toHaveBeenCalledWith([
      {
        field: 'environment',
        reason: 'Addresses your note about the environment.',
        new_value: 'a Mumbai fabrication yard',
      },
    ]);
  });

  it('lets someone without approval rights read the plan but not decide it', () => {
    render(<RevisionPlanCard {...props({ capabilities: designer })} />);
    expect(screen.getByText('Setting')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Create revised version' })).toBeNull();
    expect(screen.getByText(/needs approval rights/i)).toBeTruthy();
  });
});

describe('RevisedPlanCard', () => {
  it('shows the stored before and after, per version', () => {
    render(
      <RevisedPlanCard
        diff={revision().diff}
        fromVersion={2}
        toVersion={3}
        busy={false}
        capabilities={admin}
        onApprove={noop}
        onDiscard={noop}
      />,
    );
    expect(screen.getByRole('heading', { name: 'Creative plan v3' })).toBeTruthy();
    expect(screen.getByText('v2')).toBeTruthy();
    expect(screen.getByText('a fabrication floor')).toBeTruthy();
    expect(screen.getByText(/unchanged from v2, which still exists/)).toBeTruthy();
  });
});

// --------------------------------------------------------------- protection

describe('ProtectedPanel', () => {
  it('lists only what the backend reports as protected', () => {
    const spec = { locked_fields: ['cta', 'negative_constraints'] } as CreativeSpecification;
    render(<ProtectedPanel groups={protectedFields(delta(), spec)} />);
    expect(screen.getByText('Protected by Campaign OS')).toBeTruthy();
    expect(screen.getByText('Call to action')).toBeTruthy();
    expect(screen.getByText('Things that must not appear')).toBeTruthy();
    expect(screen.getByText(/remain protected while the creative is revised/)).toBeTruthy();
  });

  it('renders nothing at all rather than a reassuring empty panel', () => {
    const { container } = render(<ProtectedPanel groups={protectedFields(null, null)} />);
    expect(container.textContent).toBe('');
  });

  it('calls out a lock the feedback asked to lift', () => {
    const spec = { locked_fields: ['cta'] } as CreativeSpecification;
    render(<ProtectedPanel groups={protectedFields(delta({ explicit_unlocks: ['cta'] }), spec)} />);
    expect(screen.getByText('Unlocked because you asked')).toBeTruthy();
  });
});

describe('LocalizationPanel', () => {
  it('shows the market context and why a revision cannot move it', () => {
    render(<LocalizationPanel context={localizationContext(campaignSpec)} />);
    expect(screen.getByText('Localization preserved')).toBeTruthy();
    expect(screen.getByText('Mumbai, Maharashtra')).toBeTruthy();
    expect(screen.getByText('the FS-9 panel')).toBeTruthy();
    expect(screen.getByText('monsoon imagery')).toBeTruthy();
    expect(screen.getByText(/without changing the market context/)).toBeTruthy();
  });

  it('renders nothing when the brief records no market context', () => {
    const { container } = render(<LocalizationPanel context={localizationContext(null)} />);
    expect(container.textContent).toBe('');
  });
});

// ------------------------------------------------------------- the loop

describe('GuardianLoop', () => {
  it('shows that an approved revision still has to be generated and checked', () => {
    const state = refinementState(revision({ current: record({ status: 'APPROVED' }) }));
    render(<GuardianLoop state={state} />);
    expect(screen.getByText('Generate again')).toBeTruthy();
    expect(screen.getByText('Brand check')).toBeTruthy();
    expect(screen.getByText(/not been brand-checked/i)).toBeTruthy();
  });

  it('marks only the steps that have actually happened', () => {
    const state = refinementState(revision({ current: null, history: [] }));
    render(<GuardianLoop state={state} />);
    expect(screen.queryAllByText('— done', { exact: false })).toHaveLength(0);
  });
});

// ---------------------------------------------------------------- versions

describe('VersionHistory', () => {
  it('lists every version, newest first, with what it changed', () => {
    render(<VersionHistory versions={timeline()} selectedAssetId={null} />);
    const headings = screen.getAllByRole('heading', { level: 4 }).map((h) => h.textContent);
    expect(headings[0]).toMatch(/^v3/);
    expect(headings[1]).toMatch(/^v2/);
    expect(screen.getByText('Setting')).toBeTruthy();
  });

  it('marks the plan in force', () => {
    render(<VersionHistory versions={timeline()} selectedAssetId={null} />);
    expect(screen.getByText('Current plan')).toBeTruthy();
  });

  it('never names who made a change', () => {
    render(<VersionHistory versions={timeline()} selectedAssetId={null} />);
    // `requested_by` is not projected, so the record says what it knows.
    expect(screen.getByText('Revision recorded')).toBeTruthy();
    expect(screen.getByText('“Make the setting feel local.”')).toBeTruthy();
    expect(screen.queryByText(/\bby [A-Z]/)).toBeNull();
  });

  it('reports a version nobody checked as unchecked, never as a pass', () => {
    render(<VersionHistory versions={timeline()} selectedAssetId={null} />);
    // v2 has no guardian result stamped with it in this fixture.
    expect(screen.getByText('Not brand-checked')).toBeTruthy();
  });

  it('does not call the earliest version it knows about the initial one', () => {
    // The timeline holds the versions rows actually stamp. On a live campaign
    // v1 exists in the database with nothing pointing at it, so the earliest
    // entry shown is v2 — and calling that "initial" would be a claim.
    render(<VersionHistory versions={timeline()} selectedAssetId={null} />);
    expect(screen.queryByText('Initial creative plan')).toBeNull();
    expect(screen.getByText('No revision recorded for this version')).toBeTruthy();
  });

  it('does call v1 the initial plan, because that one is true by definition', () => {
    const versions = versionTimeline(
      null,
      null,
      generation({ assets: [asset({ specification_version: 1 })], specification_version: 1 }),
      null,
    );
    render(<VersionHistory versions={versions} selectedAssetId={null} />);
    expect(screen.getByText('Initial creative plan')).toBeTruthy();
  });

  it('says when a version produced nothing, which is the state after a revision', () => {
    render(<VersionHistory versions={timeline()} selectedAssetId={null} />);
    expect(screen.getByText('Nothing generated from it')).toBeTruthy();
  });

  it('shows a version’s own plates, through signed URLs', () => {
    render(<VersionHistory versions={timeline()} selectedAssetId={null} />);
    for (const img of screen.getAllByRole('img')) {
      expect(img.getAttribute('src')).toContain('token=');
    }
  });

  it('says so when a campaign has no versions yet', () => {
    render(<VersionHistory versions={[]} selectedAssetId={null} />);
    expect(screen.getByText(/No plan versions yet/)).toBeTruthy();
  });

  it('offers a comparison only where a revision joins two versions', () => {
    render(<VersionHistory versions={timeline()} selectedAssetId={null} />);
    expect(screen.getAllByRole('button', { name: /^Compare/ })).toHaveLength(1);
    expect(screen.getByRole('button', { name: 'Compare v2 with v3' })).toBeTruthy();
  });
});

describe('the version comparison', () => {
  function open() {
    render(<VersionHistory versions={timeline()} selectedAssetId={null} />);
    fireEvent.click(screen.getByRole('button', { name: 'Compare v2 with v3' }));
  }

  it('announces its state with pressed semantics, not colour', () => {
    render(<VersionHistory versions={timeline()} selectedAssetId={null} />);
    const toggle = screen.getByRole('button', { name: 'Compare v2 with v3' });
    expect(toggle.getAttribute('aria-pressed')).toBe('false');
    fireEvent.click(toggle);
    expect(
      screen.getByRole('button', { name: 'Hide the comparison' }).getAttribute('aria-pressed'),
    ).toBe('true');
  });

  it('shows what changed and what stayed', () => {
    open();
    const panel = screen.getByRole('heading', { name: 'v2 compared with v3' }).closest('div')!
      .parentElement!;
    expect(within(panel).getByText('What changed')).toBeTruthy();
    expect(within(panel).getByText('What stayed')).toBeTruthy();
    expect(within(panel).getByText('How the product appears')).toBeTruthy();
  });

  it('carries each version’s own brand standing, never one inherited', () => {
    open();
    expect(screen.getAllByText('Not brand-checked').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Within the brand’s rules').length).toBeGreaterThan(0);
    expect(screen.getByText(/never brand-checked, so only v3/)).toBeTruthy();
  });

  it('says a version has no visual rather than borrowing the other side’s', () => {
    open();
    expect(screen.getByText('Nothing generated from v2')).toBeTruthy();
  });

  it('becomes a toggle where two columns would not fit', () => {
    open();
    const group = screen.getByRole('group', { name: 'Which version to show' });
    const buttons = within(group).getAllByRole('button');
    expect(buttons.map((b) => b.textContent)).toEqual(['v2', 'v3']);
    expect(buttons[1]!.getAttribute('aria-pressed')).toBe('true');
    fireEvent.click(buttons[0]!);
    expect(buttons[0]!.getAttribute('aria-pressed')).toBe('true');
    expect(buttons[1]!.getAttribute('aria-pressed')).toBe('false');
  });

  it('closes again', () => {
    open();
    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(screen.queryByRole('heading', { name: 'v2 compared with v3' })).toBeNull();
  });
});

// -------------------------------------------------------------- crosscutting

describe('the refinement surfaces — accessibility and motion', () => {
  it('reaches every action with a keyboard, because every action is a button', () => {
    render(<VersionHistory versions={timeline()} selectedAssetId={null} />);
    for (const button of screen.getAllByRole('button')) expect(button.tagName).toBe('BUTTON');
  });

  it('labels the note field, so it is not an unnamed box', () => {
    render(
      <RevisionRequest
        busy={false}
        capabilities={admin}
        attachedAsset={null}
        onDetach={noop}
        onSubmit={noop}
      />,
    );
    expect(screen.getByLabelText('What would you like to change?').tagName).toBe('TEXTAREA');
  });

  it('animates through the classes the global reduced-motion rule governs', () => {
    // Motion is CSS: `globals.css` collapses `.arrive` and the rail under
    // `prefers-reduced-motion`, so what a component owes is the hook, and
    // content already in its final DOM position.
    const { container } = render(
      <VersionHistory versions={timeline()} selectedAssetId={null} />,
    );
    expect(container.querySelector('.version-rail')).toBeTruthy();
    expect(container.querySelectorAll('.arrive').length).toBeGreaterThan(0);
    expect(screen.getByText('Current plan')).toBeTruthy();
  });

  it('gives the timeline list semantics, so its length is announced', () => {
    render(<VersionHistory versions={timeline()} selectedAssetId={null} />);
    expect(screen.getAllByRole('listitem').length).toBeGreaterThanOrEqual(2);
  });
});
