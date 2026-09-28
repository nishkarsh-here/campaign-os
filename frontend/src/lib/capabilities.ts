/**
 * What the person in front of us is allowed to do.
 *
 * Screens ask `can('approve')`, never `role === 'admin'`. Two reasons: the role
 * vocabulary has five values today and will grow, and a screen that tests a
 * role name has quietly invented its own access rule. One map, one question.
 *
 * ---
 *
 * **This is presentation, not security — and the distinction matters.**
 *
 * No endpoint in the API differentiates by role. `app/api/deps.py` resolves the
 * caller's `Principal.role` and refuses non-members, but every mutating route
 * accepts a `viewer` exactly as it accepts an `admin`. So hiding a control here
 * tidies the interface; it does not protect anything.
 *
 * The reason to do it anyway is honesty toward the user: an Approve button that
 * a person is not supposed to press is worse than no button, because when it
 * works they learn the roles are decorative, and when it eventually fails they
 * learn the interface lies. This map is also the shape the backend needs, so
 * server-side enforcement can land without a UI redesign.
 *
 * Until that lands, nothing in this product may claim role-based access
 * control. Tracked as audit finding H-5.
 */

/** The five values `memberships.role` permits — see `app/db/models.py`. */
export type Role = 'admin' | 'brand_manager' | 'marketing' | 'designer' | 'viewer';

export type Capability =
  /** Create and edit campaigns, briefs, references, creative plans. */
  | 'edit_campaign'
  /** Ask for another round on a generated creative. */
  | 'request_revision'
  /** Pass a human approval gate — strategy, creative plan, brand check. */
  | 'approve'
  /** Change what the brand asserts: claims, palette, accepted facts. */
  | 'edit_brand'
  /** Create projects, and manage who is in the organization. */
  | 'manage_workspace';

const MATRIX: Record<Role, readonly Capability[]> = {
  admin: ['edit_campaign', 'request_revision', 'approve', 'edit_brand', 'manage_workspace'],
  brand_manager: ['edit_campaign', 'request_revision', 'approve', 'edit_brand'],
  marketing: ['edit_campaign', 'request_revision', 'approve'],
  // A designer makes and revises work but does not sign it off; that is the
  // separation the approval gates exist to create.
  designer: ['edit_campaign', 'request_revision'],
  viewer: [],
};

/**
 * Read a role string from the API.
 *
 * Unknown values fall to `viewer` — the least privileged reading. Failing
 * closed on an unrecognised role means a new backend role shows too few
 * controls rather than too many.
 */
export function asRole(value: string | null | undefined): Role {
  return value && value in MATRIX ? (value as Role) : 'viewer';
}

export interface Capabilities {
  role: Role;
  can: (capability: Capability) => boolean;
  /** True while `/me` has not answered; screens show neither yes nor no. */
  unknown: boolean;
}

export function capabilitiesFor(role: string | null | undefined): Capabilities {
  const resolved = asRole(role);
  const granted = MATRIX[resolved];
  return {
    role: resolved,
    can: (capability) => granted.includes(capability),
    unknown: role == null,
  };
}

/** Human-readable role names, for the one place the role is displayed. */
export const ROLE_LABEL: Record<Role, string> = {
  admin: 'Admin',
  brand_manager: 'Brand manager',
  marketing: 'Marketing',
  designer: 'Designer',
  viewer: 'Viewer',
};
