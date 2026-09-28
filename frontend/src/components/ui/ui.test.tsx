// @vitest-environment jsdom

/**
 * The primitives' contracts.
 *
 * These assert behaviour and accessibility, not appearance. A snapshot of a
 * class string would fail on every deliberate restyle and pass on every
 * regression that matters — the opposite of useful. What is pinned here is what
 * UI-2 and UI-3 must not break while they change how things look: a button that
 * does not submit a form by surprise, a status that is readable without colour,
 * an error that announces itself, a label that is actually attached to its
 * control.
 */

import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Field,
  Input,
  SectionHeader,
  StatusBadge,
} from './index';

// --------------------------------------------------------------------- Button
describe('Button', () => {
  it('is a real button with an accessible name', () => {
    render(<Button>Create project</Button>);
    expect(screen.getByRole('button', { name: 'Create project' })).toBeDefined();
  });

  it('does not submit a form unless it is asked to', () => {
    // A `<button>` with no type defaults to submit. Inside the product's
    // several forms, a "Cancel" or "Add reference" button that quietly submitted
    // its form would be a genuine bug, so the primitive defaults the other way.
    const submit = vi.fn((e: React.FormEvent) => e.preventDefault());
    render(
      <form onSubmit={submit}>
        <Button>Not a submit</Button>
      </form>,
    );
    fireEvent.click(screen.getByRole('button'));
    expect(submit).not.toHaveBeenCalled();
  });

  it('submits when it is explicitly a submit button', () => {
    const submit = vi.fn((e: React.FormEvent) => e.preventDefault());
    render(
      <form onSubmit={submit}>
        <Button type="submit">Create</Button>
      </form>,
    );
    fireEvent.click(screen.getByRole('button'));
    expect(submit).toHaveBeenCalledOnce();
  });

  it('is disabled to assistive technology as well as to the mouse', () => {
    const onClick = vi.fn();
    render(
      <Button disabled onClick={onClick}>
        Create
      </Button>,
    );
    const button = screen.getByRole('button');
    expect((button as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });

  it('distinguishes its variants', () => {
    // Not a snapshot: only that primary and secondary resolve differently, so a
    // refactor cannot collapse the two into one look.
    const { container: primary } = render(<Button variant="primary">A</Button>);
    const { container: secondary } = render(<Button variant="secondary">B</Button>);
    expect(primary.firstElementChild?.className).not.toBe(secondary.firstElementChild?.className);
  });

  it('keeps a caller className instead of being overwritten by it', () => {
    render(<Button className="mt-4">A</Button>);
    const cls = screen.getByRole('button').className;
    expect(cls).toContain('mt-4');
    expect(cls).toContain('rounded-md');
  });
});

// ----------------------------------------------------------------------- Card
describe('Card', () => {
  it('pads its content by default', () => {
    const { container } = render(<Card>body</Card>);
    expect(container.firstElementChild?.className).toContain('p-5');
  });

  it('yields padding to content that owns its own spacing', () => {
    // A divided list supplies per-row padding; an outer p-5 double-insets it.
    const { container } = render(<Card padding={false}>body</Card>);
    expect(container.firstElementChild?.className).not.toContain('p-5');
  });

  it('renders the element the layout needs, so it can sit inside a list', () => {
    render(
      <ul>
        <Card as="li">row</Card>
      </ul>,
    );
    expect(screen.getByRole('listitem')).toBeDefined();
  });

  it('forwards accessibility attributes', () => {
    render(<Card as="section" aria-label="Projects" />);
    expect(screen.getByRole('region', { name: 'Projects' })).toBeDefined();
  });
});

// -------------------------------------------------------------- SectionHeader
describe('SectionHeader', () => {
  it('lets the page choose the heading rank', () => {
    // Rank is document structure and belongs to the page: a fixed <h2> is how an
    // outline ends up skipping levels.
    render(<SectionHeader level={1} title="Projects" />);
    expect(screen.getByRole('heading', { level: 1, name: 'Projects' })).toBeDefined();
  });

  it('defaults to a section-level heading', () => {
    render(<SectionHeader title="Brand facts" />);
    expect(screen.getByRole('heading', { level: 2, name: 'Brand facts' })).toBeDefined();
  });
});

// ----------------------------------------------------------- Badge / status
describe('StatusBadge', () => {
  it('never communicates status by colour alone', () => {
    // The single most important contract here. A tone must always arrive with a
    // word, for a colour-blind reader and for a washed-out projector.
    render(<StatusBadge tone="positive">Approved</StatusBadge>);
    expect(screen.getByText('Approved').textContent?.trim()).toBe('Approved');
  });

  it('draws its colour from theme tokens, not a fixed palette shade', () => {
    // Regression guard for a real defect: the hard-coded `-400` shades were
    // legible on the dark theme and roughly 1.8:1 on the light one. Tokens
    // resolve per theme; a fixed shade cannot.
    const tones = ['positive', 'caution', 'negative', 'active', 'neutral'] as const;
    for (const tone of tones) {
      const { container } = render(<StatusBadge tone={tone}>Word</StatusBadge>);
      const cls = container.firstElementChild?.className ?? '';
      expect(cls).not.toMatch(/emerald|amber|sky|red-\d|green-\d/);
    }
  });

  it('treats a tooltip as a supplement, not as the meaning', () => {
    render(
      <StatusBadge tone="active" title="Mock providers only">
        Demo mode
      </StatusBadge>,
    );
    // The word is present with or without the tooltip ever being hovered.
    expect(screen.getByText('Demo mode')).toBeDefined();
  });

  it('is visually distinct from a plain count badge', () => {
    const { container: status } = render(<StatusBadge tone="positive">Passed</StatusBadge>);
    const { container: plain } = render(<Badge>v3</Badge>);
    expect(status.firstElementChild?.className).not.toBe(plain.firstElementChild?.className);
  });
});

// ----------------------------------------------------------------- ErrorState
describe('ErrorState', () => {
  it('announces itself rather than only being drawn', () => {
    render(<ErrorState message="The campaign could not be loaded." />);
    expect(screen.getByRole('alert').textContent).toContain('The campaign could not be loaded.');
  });

  it('offers a retry when the failure is retryable', () => {
    const onRetry = vi.fn();
    render(<ErrorState message="Timed out." onRetry={onRetry} />);
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it('offers no retry when the caller gave no way to retry', () => {
    render(<ErrorState message="Timed out." />);
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('does not offer to retry a permission failure', () => {
    // Retrying a FORBIDDEN response fails identically. A button that cannot
    // work teaches people that buttons here are decorative.
    render(<ErrorState code="FORBIDDEN" message="You do not belong to any organization yet." />);
    expect(screen.queryByRole('button', { name: 'Try again' })).toBeNull();
    expect(screen.getByRole('link', { name: 'Back to your workspace' })).toBeDefined();
  });

  it('gives a permission failure its own title', () => {
    render(<ErrorState code="FORBIDDEN" message="No access." title="Cannot load campaigns" />);
    expect(screen.getByRole('heading').textContent).toBe('You do not have access to this');
  });

  it('surfaces the request id so a user can quote it', () => {
    render(<ErrorState message="Failed." requestId="req-abc123" />);
    expect(screen.getByRole('alert').textContent).toContain('req-abc123');
  });
});

// ----------------------------------------------------------------- EmptyState
describe('EmptyState', () => {
  it('explains the emptiness and offers the way out of it', () => {
    render(
      <EmptyState
        title="No projects yet"
        description="A project holds a brand and the campaigns you run for it."
        action={<Button>Create project</Button>}
      />,
    );
    expect(screen.getByRole('heading', { name: 'No projects yet' })).toBeDefined();
    expect(screen.getByText(/A project holds a brand/)).toBeDefined();
    expect(screen.getByRole('button', { name: 'Create project' })).toBeDefined();
  });

  it('is not mistaken for an error', () => {
    // Nothing has gone wrong, so nothing should be announced as a problem.
    render(<EmptyState title="No brands yet" description="Add one to begin." />);
    expect(screen.queryByRole('alert')).toBeNull();
  });
});

// ---------------------------------------------------------------------- Field
describe('Field', () => {
  it('connects its label to the control it wraps', () => {
    // `getByLabelText` only succeeds when the association is real, which is the
    // same association a screen reader and a label click depend on.
    render(
      <Field label="New project">
        <Input />
      </Field>,
    );
    expect(screen.getByLabelText('New project')).toBeDefined();
  });

  it('describes the control with its hint, which survives typing', () => {
    render(
      <Field label="Brand name" hint="Shown on every asset.">
        <Input />
      </Field>,
    );
    const input = screen.getByLabelText('Brand name');
    const describedBy = input.getAttribute('aria-describedby');
    expect(describedBy).toBeTruthy();
    expect(document.getElementById(describedBy!)?.textContent).toBe('Shown on every asset.');
  });

  it('marks the control invalid and announces the reason', () => {
    render(
      <Field label="Brand name" error="A name is required.">
        <Input />
      </Field>,
    );
    expect(screen.getByLabelText('Brand name').getAttribute('aria-invalid')).toBe('true');
    expect(screen.getByRole('alert').textContent).toBe('A name is required.');
  });

  it('claims nothing is wrong when nothing is', () => {
    render(
      <Field label="Brand name">
        <Input />
      </Field>,
    );
    expect(screen.getByLabelText('Brand name').getAttribute('aria-invalid')).toBeNull();
  });

  it('gives each instance its own ids, so two fields on a page stay distinct', () => {
    render(
      <>
        <Field label="First">
          <Input />
        </Field>
        <Field label="Second">
          <Input />
        </Field>
      </>,
    );
    const first = screen.getByLabelText('First');
    const second = screen.getByLabelText('Second');
    expect(first.id).not.toBe(second.id);
    expect(first).not.toBe(second);
  });
});
