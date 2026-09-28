/**
 * The capability model.
 *
 * Worth pinning because the failure mode is silent in both directions: a
 * capability granted too widely shows a control that will not work, and one
 * granted too narrowly hides a control someone needs with no error to explain
 * it.
 */

import { describe, expect, it } from 'vitest';
import { ROLE_LABEL, asRole, capabilitiesFor } from '@/lib/capabilities';

describe('reading a role', () => {
  it('accepts every role the database permits', () => {
    // `ROLES` in app/db/models.py, enforced by the `role_valid` check
    // constraint. A role the backend can store and this cannot read would
    // silently become a viewer.
    for (const role of ['admin', 'brand_manager', 'marketing', 'designer', 'viewer'] as const) {
      expect(asRole(role)).toBe(role);
    }
  });

  it('fails closed on anything it does not recognise', () => {
    // A role added to the backend later shows too few controls, not too many.
    expect(asRole('owner')).toBe('viewer');
    expect(asRole('')).toBe('viewer');
    expect(asRole(undefined)).toBe('viewer');
    expect(asRole(null)).toBe('viewer');
  });
});

describe('what each role may do', () => {
  it('lets an admin do everything', () => {
    const { can } = capabilitiesFor('admin');
    for (const capability of [
      'edit_campaign',
      'request_revision',
      'approve',
      'edit_brand',
      'manage_workspace',
    ] as const) {
      expect(can(capability)).toBe(true);
    }
  });

  it('gives a viewer no controls at all', () => {
    const { can } = capabilitiesFor('viewer');
    expect(can('edit_campaign')).toBe(false);
    expect(can('approve')).toBe(false);
    expect(can('edit_brand')).toBe(false);
    expect(can('manage_workspace')).toBe(false);
  });

  it('separates making work from signing it off', () => {
    // A designer produces and revises but does not approve — that separation is
    // the reason the approval gates exist at all.
    const designer = capabilitiesFor('designer');
    expect(designer.can('edit_campaign')).toBe(true);
    expect(designer.can('request_revision')).toBe(true);
    expect(designer.can('approve')).toBe(false);
  });

  it('keeps brand truth away from campaign work', () => {
    // Marketing runs campaigns and approves gates; changing what the brand
    // asserts is a brand manager's decision.
    const marketing = capabilitiesFor('marketing');
    expect(marketing.can('approve')).toBe(true);
    expect(marketing.can('edit_brand')).toBe(false);

    const brandManager = capabilitiesFor('brand_manager');
    expect(brandManager.can('edit_brand')).toBe(true);
    expect(brandManager.can('manage_workspace')).toBe(false);
  });

  it('reserves member and project management for an admin', () => {
    for (const role of ['brand_manager', 'marketing', 'designer', 'viewer'] as const) {
      expect(capabilitiesFor(role).can('manage_workspace')).toBe(false);
    }
  });
});

describe('before the caller is known', () => {
  it('reports unknown rather than assuming a role', () => {
    // While `/me` is in flight a screen must show neither the control nor a
    // "you cannot do this" — both would be a claim we cannot yet make.
    const pending = capabilitiesFor(null);
    expect(pending.unknown).toBe(true);
    expect(pending.can('approve')).toBe(false);

    expect(capabilitiesFor('viewer').unknown).toBe(false);
  });
});

describe('role names on screen', () => {
  it('names every role in the user’s words', () => {
    expect(ROLE_LABEL.brand_manager).toBe('Brand manager');
    for (const label of Object.values(ROLE_LABEL)) expect(label).not.toContain('_');
  });
});
