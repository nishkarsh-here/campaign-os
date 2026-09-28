/**
 * What a campaign's status means to a person, and whether it is waiting on one.
 *
 * Derived from `Campaign.status` alone — a field every campaign in a list
 * already carries. The alternative would be fetching each campaign's full
 * summary to read `next_action`, which on an organization with sixteen
 * campaigns is sixteen requests to render one list. The stage-level next action
 * lives on the command centre, where one campaign is in view and one request is
 * the right cost.
 *
 * `CampaignStatus` covers the discovery phase only, which is a real limit worth
 * stating: the backend's campaign row does not advance past
 * `SPECIFICATION_CONFIRMED` as creative, generation and composition proceed —
 * those live in their own tables. So a confirmed campaign reads "Ready for
 * creative" here and the command centre is where its true stage is shown.
 */

import type { CampaignStatus } from '@/lib/api';
import type { Tone } from '@/components/ui';

export interface StatusMeaning {
  /** The user's words. Never the enum. */
  label: string;
  tone: Tone;
  /** True when a person has to do something before anything else can happen. */
  awaitsHuman: boolean;
  /** What that person should do, where the status implies it. */
  invitation: string | null;
}

const MEANING: Record<CampaignStatus, StatusMeaning> = {
  DRAFT: {
    label: 'Brief not started',
    tone: 'neutral',
    awaitsHuman: true,
    invitation: 'Start the brief',
  },
  INTERVIEWING: {
    label: 'Brief in progress',
    tone: 'active',
    awaitsHuman: true,
    invitation: 'Continue the brief',
  },
  SPECIFICATION_READY: {
    label: 'Brief awaiting your confirmation',
    tone: 'caution',
    awaitsHuman: true,
    invitation: 'Review and confirm the brief',
  },
  SPECIFICATION_CONFIRMED: {
    label: 'Brief confirmed',
    tone: 'positive',
    awaitsHuman: false,
    invitation: null,
  },
  FAILED: {
    label: 'Failed',
    tone: 'negative',
    awaitsHuman: true,
    invitation: 'Open the campaign to see why',
  },
  CANCELLED: { label: 'Cancelled', tone: 'neutral', awaitsHuman: false, invitation: null },
};

/**
 * Unknown statuses fall back to the raw value, humanised.
 *
 * A status the backend adds later should read oddly, not crash the list — and
 * it must not be silently reported as one of the states we do know.
 */
export function statusMeaning(status: string): StatusMeaning {
  return (
    MEANING[status as CampaignStatus] ?? {
      label: status.replace(/_/g, ' ').toLowerCase(),
      tone: 'neutral' as Tone,
      awaitsHuman: false,
      invitation: null,
    }
  );
}
