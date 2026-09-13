import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'campaign-os',
  description: 'From brainstorm to brand-ready campaign.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  );
}
