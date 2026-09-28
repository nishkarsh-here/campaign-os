/**
 * Status meaning.
 *
 * The home screen's "waiting on you" list is built entirely from this, so an
 * error here silently hides work from the person who has to do it.
 */

import { describe, expect, it } from 'vitest';
import { statusMeaning } from '@/lib/campaign-status';

describe('status meaning', () => {
  it('says which statuses are waiting on a person', () => {
    expect(statusMeaning('DRAFT').awaitsHuman).toBe(true);
    expect(statusMeaning('INTERVIEWING').awaitsHuman).toBe(true);
    expect(statusMeaning('SPECIFICATION_READY').awaitsHuman).toBe(true);
    expect(statusMeaning('FAILED').awaitsHuman).toBe(true);
  });

  it('does not nag about a campaign that has moved on', () => {
    // A confirmed brief is the graph's turn, not a person's.
    expect(statusMeaning('SPECIFICATION_CONFIRMED').awaitsHuman).toBe(false);
    expect(statusMeaning('CANCELLED').awaitsHuman).toBe(false);
  });

  it('gives every waiting status something to actually do', () => {
    for (const status of ['DRAFT', 'INTERVIEWING', 'SPECIFICATION_READY', 'FAILED'] as const) {
      expect(statusMeaning(status).invitation).toBeTruthy();
    }
  });

  it('never shows the enum to a reader', () => {
    for (const status of [
      'DRAFT',
      'INTERVIEWING',
      'SPECIFICATION_READY',
      'SPECIFICATION_CONFIRMED',
      'FAILED',
      'CANCELLED',
    ] as const) {
      const { label } = statusMeaning(status);
      expect(label).not.toMatch(/_/);
      expect(label).not.toBe(status);
    }
  });

  it('degrades gracefully on a status it has never seen', () => {
    // A status the backend adds later should read oddly, not crash a list —
    // and must not be reported as one of the states we do know.
    const meaning = statusMeaning('AWAITING_LEGAL');
    expect(meaning.label).toBe('awaiting legal');
    expect(meaning.awaitsHuman).toBe(false);
    expect(meaning.invitation).toBeNull();
  });
});
