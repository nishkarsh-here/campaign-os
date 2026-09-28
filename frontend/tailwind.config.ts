import type { Config } from 'tailwindcss';

/**
 * The token surface.
 *
 * Every name here resolves to a CSS variable declared in `globals.css`, so a
 * value is defined exactly once and both themes get it. Nothing in `src/`
 * should need a raw hex code or an arbitrary `text-[11px]` again.
 *
 * This `extend`s rather than replaces Tailwind's scales on purpose. The
 * numeric spacing scale (`px-6`, `gap-3`) and the base type scale (`text-sm`,
 * `text-xs`) are already load-bearing across thirteen screens; removing them to
 * force the named tokens through would be a rewrite disguised as a config
 * change. New code uses the named tokens; existing code keeps rendering
 * byte-identically until its own phase.
 */
const config: Config = {
  content: ['./src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      // ----------------------------------------------------------- colour
      colors: {
        surface: 'rgb(var(--surface) / <alpha-value>)',
        card: 'rgb(var(--card) / <alpha-value>)',
        raised: 'rgb(var(--raised) / <alpha-value>)',
        ink: 'rgb(var(--ink) / <alpha-value>)',
        muted: 'rgb(var(--muted) / <alpha-value>)',
        line: 'rgb(var(--line) / <alpha-value>)',
        // No `accent.ink`: nothing in the product places text on an accent
        // fill, and a defined-but-unused token is how the original dead
        // `accent` came about. It comes back when a surface needs it.
        accent: 'rgb(var(--accent) / <alpha-value>)',
        success: 'rgb(var(--success) / <alpha-value>)',
        warning: 'rgb(var(--warning) / <alpha-value>)',
        danger: 'rgb(var(--danger) / <alpha-value>)',
        info: 'rgb(var(--info) / <alpha-value>)',
        focus: 'rgb(var(--focus) / <alpha-value>)',
      },

      // ------------------------------------------------------- typography
      fontFamily: {
        // Set by next/font in the root layout; the fallback list is what
        // renders if the bundled file is ever unavailable.
        sans: ['var(--font-sans)', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      /**
       * A named scale, each step carrying its own line height and tracking so
       * a heading cannot be half-applied. Tight tracking on the large steps and
       * open tracking on `label` are the two things that make a UI type scale
       * read as designed rather than as defaults.
       *
       * `body` is 14px because that is the density the application already has
       * (`text-sm` is its most common class by a wide margin); making `body`
       * 16px here would silently loosen every screen that adopts it.
       */
      fontSize: {
        display: ['2.25rem', { lineHeight: '1.1', letterSpacing: '-0.02em', fontWeight: '600' }],
        h1: ['1.75rem', { lineHeight: '1.2', letterSpacing: '-0.018em', fontWeight: '600' }],
        h2: ['1.25rem', { lineHeight: '1.3', letterSpacing: '-0.012em', fontWeight: '600' }],
        h3: ['1rem', { lineHeight: '1.4', letterSpacing: '-0.006em', fontWeight: '600' }],
        body: ['0.875rem', { lineHeight: '1.6' }],
        small: ['0.8125rem', { lineHeight: '1.5' }],
        caption: ['0.75rem', { lineHeight: '1.5' }],
        // Replaces 54 hand-written copies of `text-[10px] uppercase
        // tracking-wide`. The component adds `uppercase`, which a fontSize
        // entry cannot carry.
        label: ['0.6875rem', { lineHeight: '1.3', letterSpacing: '0.06em', fontWeight: '500' }],
      },

      // ---------------------------------------------------------- spacing
      /**
       * Named steps alongside the numeric scale, for the places where "this is
       * a section gap" is the real intent. Deliberately six values: a scale
       * with a step for every occasion is how arbitrary values come back.
       */
      spacing: {
        xs: '0.25rem',
        sm: '0.5rem',
        md: '1rem',
        lg: '1.5rem',
        xl: '2rem',
        '2xl': '3rem',
        gutter: '1rem', // page edge on mobile
        'gutter-lg': '1.5rem', // page edge from `sm` up
        section: '2.5rem', // between major blocks on a page
        sidebar: '15rem', // reserved for UI-2's navigation
      },

      // ----------------------------------------------------------- radius
      /**
       * Values identical to what the screens render today, named so UI-3 can
       * retune every corner in the product from one place. Tokenising a value
       * and changing it are two separate changes; this phase does the first.
       */
      borderRadius: {
        sm: '0.25rem',
        md: '0.375rem',
        lg: '0.5rem',
        full: '9999px',
      },

      // -------------------------------------------------------- elevation
      /**
       * Three steps, named `elevated` rather than `card` on purpose: `card` is
       * also a colour token, and Tailwind resolves `shadow-card` as a
       * shadow-*colour* utility when both exist — which silently emitted a
       * white shadow, i.e. no shadow at all. A token namespace collision is
       * invisible in the source and only visible in the compiled CSS.
       */
      boxShadow: {
        subtle: '0 1px 2px 0 rgb(var(--shadow-color) / var(--shadow-strength))',
        elevated: '0 1px 3px 0 rgb(var(--shadow-color) / var(--shadow-strength)), 0 1px 2px -1px rgb(var(--shadow-color) / var(--shadow-strength))',
        modal:
          '0 10px 30px -10px rgb(var(--shadow-color) / calc(var(--shadow-strength) * 2)), 0 2px 8px -2px rgb(var(--shadow-color) / var(--shadow-strength))',
      },

      // ----------------------------------------------------------- motion
      transitionDuration: {
        instant: 'var(--motion-instant)',
        fast: 'var(--motion-fast)',
        base: 'var(--motion-base)',
        slow: 'var(--motion-slow)',
      },
      transitionTimingFunction: {
        out: 'var(--ease-out)',
      },

      // ----------------------------------------------------------- layout
      maxWidth: {
        page: '64rem', // the shell's content width — what `max-w-5xl` was
        content: '46rem', // prose and single-column forms
        narrow: '26rem', // sign-in and other focused tasks
      },
    },
  },
  plugins: [],
};
export default config;
