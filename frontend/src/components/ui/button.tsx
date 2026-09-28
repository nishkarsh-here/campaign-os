/**
 * The button.
 *
 * Before this there were 64 `<button>` elements in the application carrying
 * roughly seventeen distinct class strings for what were really two variants at
 * three sizes — `text-sm` here and `text-xs` there, `hover:bg-line/40` on one
 * screen and `hover:bg-line/30` on the next, `disabled:opacity-40` beside
 * `disabled:opacity-50`. None of that was a decision; it was drift.
 *
 * The variant classes reproduce what the screens already render, so adopting
 * this changes no button's appearance — only where its appearance is decided.
 */

import { cx } from './cx';

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';
export type ButtonSize = 'sm' | 'md' | 'lg';

const VARIANT: Record<ButtonVariant, string> = {
  primary: 'bg-ink text-surface font-medium hover:bg-ink/90',
  secondary: 'border border-line text-ink hover:bg-line/40',
  ghost: 'text-muted hover:bg-line/40 hover:text-ink',
  // Destructive actions are named by colour *and* by their label; colour alone
  // is never the signal. See `StatusBadge` for the same rule on status.
  danger: 'border border-danger/50 text-danger hover:bg-danger/10',
};

const SIZE: Record<ButtonSize, string> = {
  sm: 'px-3 py-1 text-caption',
  md: 'px-3 py-1.5 text-body',
  lg: 'px-4 py-2 text-body',
};

/**
 * The class string for a button, exposed because a good number of the
 * product's "buttons" are `<a>` or next/link elements — a link that navigates
 * must stay a link. Sharing the classes keeps those from drifting away from the
 * real buttons, which is what a second component would eventually do.
 */
export function buttonStyles(
  variant: ButtonVariant = 'secondary',
  size: ButtonSize = 'md',
  className?: string,
): string {
  return cx(
    'inline-flex items-center justify-center gap-1.5 rounded-md transition-colors',
    // Focus is handled globally by the `:focus-visible` rule in globals.css, so
    // every element gets it — including ones added after this phase.
    'disabled:cursor-not-allowed disabled:opacity-50',
    VARIANT[variant],
    SIZE[size],
    className,
  );
}

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
}

export function Button({
  variant = 'secondary',
  size = 'md',
  className,
  // Defaulted because a `<button>` inside a `<form>` with no type submits it.
  // That default has caused real bugs; an explicit one is cheap.
  type = 'button',
  ...rest
}: ButtonProps) {
  return <button type={type} className={buttonStyles(variant, size, className)} {...rest} />;
}
