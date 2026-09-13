import Link from 'next/link';

export default function Landing() {
  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col justify-center px-6">
      <p className="text-sm font-medium uppercase tracking-widest text-muted">campaign-os</p>
      <h1 className="mt-3 text-4xl font-semibold tracking-tight">
        From brainstorm to brand-ready campaign.
      </h1>
      <p className="mt-4 text-muted">
        An AI marketing orchestration platform that turns fragmented ideas, brand knowledge and
        market context into approved, multi-channel campaigns.
      </p>
      <Link
        href="/app"
        className="mt-8 w-fit rounded-md bg-ink px-4 py-2 text-sm font-medium text-surface"
      >
        Open workspace
      </Link>
    </main>
  );
}
