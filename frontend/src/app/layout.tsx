import type { Metadata } from 'next';
import localFont from 'next/font/local';
import './globals.css';

/**
 * The product typeface.
 *
 * `next/font/local` against files committed to this repository, rather than
 * `next/font/google`, for one reason: CLAUDE.md §3.5 requires the full demo to
 * run with no network access, forever. A Google-hosted font is fetched at build
 * time, which would mean a fresh clone on an offline machine could not start —
 * exactly the class of failure the mock-provider rule exists to prevent.
 *
 * Inter, variable weight, latin + latin-ext subsets (134 KB total), under the
 * SIL Open Font License. `display: 'swap'` means text is readable immediately
 * and reflows to Inter, instead of a blank page while the face loads.
 * `adjustFontFallback` matches the fallback's metrics to Inter's so that swap
 * does not shift the layout.
 */
const sans = localFont({
  src: [
    { path: './fonts/inter-latin.woff2', style: 'normal' },
    { path: './fonts/inter-latin-ext.woff2', style: 'normal' },
  ],
  variable: '--font-sans',
  display: 'swap',
  weight: '100 900',
  fallback: ['ui-sans-serif', 'system-ui', '-apple-system', 'Segoe UI', 'sans-serif'],
  adjustFontFallback: 'Arial',
});

export const metadata: Metadata = {
  title: 'campaign-os',
  description: 'From brainstorm to brand-ready campaign.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={sans.variable}>
      <body className="min-h-screen font-sans antialiased">{children}</body>
    </html>
  );
}
