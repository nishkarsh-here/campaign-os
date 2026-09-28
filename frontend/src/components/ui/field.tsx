'use client';

/**
 * Form controls, and the labelling that makes them usable.
 *
 * The application has 28 form controls. Most are labelled — either by an
 * `aria-label` or by being wrapped in a `<label>` — but the labelling decision
 * was made 28 separate times, and the control styling with it. Two of those
 * controls carry a `placeholder` as their only visible description, which
 * disappears the moment someone types.
 *
 * `Field` supplies the id, connects the label, hint and error message to the
 * control through `aria-describedby`, and sets `aria-invalid` when there is an
 * error — so the wiring is correct by construction rather than by remembering.
 * A bare `Input` still works on its own for the places that lay out their own
 * label.
 */

import { createContext, useContext, useId } from 'react';
import { cx } from './cx';

/** What a `Field` hands down to whichever control sits inside it. */
interface FieldWiring {
  id: string;
  describedBy?: string;
  invalid: boolean;
}

const FieldContext = createContext<FieldWiring | null>(null);

/**
 * The small uppercase caption used for a field label and, throughout the
 * product, for metadata keys. This replaces 54 hand-written copies of
 * `text-[10px] uppercase tracking-wide text-muted`.
 */
export function Label({
  className,
  children,
  ...rest
}: React.LabelHTMLAttributes<HTMLLabelElement>) {
  const field = useContext(FieldContext);
  return (
    <label
      // Clicking a label should focus its control. That only happens when the
      // two are actually connected.
      htmlFor={rest.htmlFor ?? field?.id}
      className={cx('block text-label uppercase text-muted', className)}
      {...rest}
    >
      {children}
    </label>
  );
}

export function Field({
  label,
  hint,
  error,
  children,
  className,
}: {
  label: React.ReactNode;
  /** Persistent help text. Survives typing, unlike a placeholder. */
  hint?: React.ReactNode;
  /** When set, the control is marked invalid and this is announced with it. */
  error?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  const base = useId();
  const hintId = hint ? `${base}-hint` : undefined;
  const errorId = error ? `${base}-error` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(' ') || undefined;

  return (
    <FieldContext.Provider value={{ id: base, describedBy, invalid: Boolean(error) }}>
      <div className={cx('space-y-1.5', className)}>
        <Label>{label}</Label>
        {children}
        {hint ? (
          <p id={hintId} className="text-caption text-muted">
            {hint}
          </p>
        ) : null}
        {error ? (
          // `role="alert"` so a validation failure is announced rather than
          // silently appearing below a control the reader has already left.
          <p id={errorId} role="alert" className="text-caption text-danger">
            {error}
          </p>
        ) : null}
      </div>
    </FieldContext.Provider>
  );
}

/** Shared control chrome, so an input and a select cannot drift apart. */
const CONTROL =
  'w-full rounded-md border border-line bg-transparent px-3 py-2 text-body text-ink ' +
  'placeholder:text-muted disabled:cursor-not-allowed disabled:opacity-60 ' +
  'aria-[invalid=true]:border-danger';

/** Reads the surrounding `Field`, if there is one. */
function useWiring(explicitId?: string) {
  const field = useContext(FieldContext);
  return {
    id: explicitId ?? field?.id,
    'aria-describedby': field?.describedBy,
    'aria-invalid': field?.invalid ? (true as const) : undefined,
  };
}

export function Input({ className, id, ...rest }: React.InputHTMLAttributes<HTMLInputElement>) {
  const wiring = useWiring(id);
  return <input {...wiring} className={cx(CONTROL, className)} {...rest} />;
}

export function Textarea({
  className,
  id,
  ref,
  ...rest
}: React.TextareaHTMLAttributes<HTMLTextAreaElement> & {
  /**
   * React 19 passes `ref` as an ordinary prop to a function component, so no
   * `forwardRef` is needed. Declared because a caller that writes into this
   * box — the refinement prompts, which append a phrase — has to put the
   * caret back afterwards.
   */
  ref?: React.Ref<HTMLTextAreaElement>;
}) {
  const wiring = useWiring(id);
  return <textarea ref={ref} {...wiring} className={cx(CONTROL, 'resize-y', className)} {...rest} />;
}

export function Select({
  className,
  id,
  children,
  ...rest
}: React.SelectHTMLAttributes<HTMLSelectElement>) {
  const wiring = useWiring(id);
  return (
    // `bg-card` rather than `bg-transparent`: a native select renders its own
    // dropdown, and `color-scheme` in globals.css is what keeps that legible in
    // dark mode.
    <select {...wiring} className={cx(CONTROL, 'bg-card', className)} {...rest}>
      {children}
    </select>
  );
}
