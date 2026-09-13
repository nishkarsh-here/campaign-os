'use client';

/**
 * The workspace: the organization's projects, and creating one.
 *
 * A project is the container campaigns live in; opening one lists them. The
 * campaign experience itself lives under /app/campaigns.
 */

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { AppShell } from '@/components/app-shell';
import { EmptyState, ErrorState, SkeletonRows } from '@/components/states';
import { ApiError, api, type Project } from '@/lib/api';
import { useWorkspace } from '@/lib/use-workspace';

export default function WorkspacePage() {
  const workspace = useWorkspace();
  const { organizationId } = workspace;

  const [projects, setProjects] = useState<Project[] | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState('');

  /**
   * Returns its own cleanup, so switching organizations cancels the in-flight
   * request instead of racing it. Without this, a slow list for org A can land
   * after org B's and repaint B's switcher over A's projects — whose links
   * then 404 under B.
   */
  const load = useCallback(() => {
    if (!organizationId) return undefined;
    const controller = new AbortController();
    setProjects(null);
    setError(null);
    api
      .listProjects(organizationId, controller.signal)
      .then((page) => {
        if (!controller.signal.aborted) setProjects(page.items);
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setError(err instanceof ApiError ? err : new ApiError('INTERNAL', String(err), 0));
      });
    return () => controller.abort();
  }, [organizationId]);

  useEffect(load, [load]);

  async function createProject(event: React.FormEvent) {
    event.preventDefault();
    if (!name.trim() || !organizationId) return;
    setCreating(true);
    setError(null);
    try {
      const project = await api.createProject(organizationId, { name: name.trim() });
      setProjects((current) => [...(current ?? []), project]);
      setName('');
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError('INTERNAL', String(err), 0));
    } finally {
      setCreating(false);
    }
  }

  // The shell itself cannot render without knowing who the caller is.
  if (workspace.loading) {
    return (
      <div className="mx-auto max-w-5xl px-6 py-10">
        <SkeletonRows rows={4} />
      </div>
    );
  }
  if (workspace.error) {
    return (
      <div className="mx-auto max-w-5xl px-6 py-10">
        <ErrorState
          title="Cannot load your workspace"
          message={workspace.error.message}
          requestId={workspace.error.requestId}
          onRetry={workspace.error.isRetryable ? workspace.reload : undefined}
        />
      </div>
    );
  }

  return (
    <AppShell
      me={workspace.me}
      activeOrganizationId={organizationId}
      onOrganizationChange={workspace.setOrganizationId}
    >
      <div className="flex items-baseline justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Projects</h1>
        <span className="text-sm text-muted">
          {projects ? `${projects.length} project${projects.length === 1 ? '' : 's'}` : ''}
        </span>
      </div>

      <form onSubmit={createProject} className="mt-6 flex gap-2">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="New project name"
          aria-label="New project name"
          className="flex-1 rounded-md border border-line bg-transparent px-3 py-2 text-sm"
        />
        <button
          type="submit"
          disabled={creating || !name.trim()}
          className="rounded-md bg-ink px-4 py-2 text-sm font-medium text-surface disabled:opacity-40"
        >
          {creating ? 'Creating…' : 'Create'}
        </button>
      </form>

      <div className="mt-8">
        {error ? (
          <ErrorState
            message={error.message}
            requestId={error.requestId}
            onRetry={error.isRetryable ? load : undefined}
          />
        ) : projects === null ? (
          <SkeletonRows />
        ) : projects.length === 0 ? (
          <EmptyState
            title="No projects yet"
            description="A project holds a brand and the campaigns you run for it. Create one to begin."
          />
        ) : (
          <ul className="divide-y divide-line rounded-lg border border-line">
            {projects.map((project) => (
              <li key={project.id}>
                <Link
                  href={`/app/projects/${project.id}`}
                  className="flex items-center justify-between px-4 py-4 hover:bg-line/20"
                >
                  <span className="text-sm font-medium">{project.name}</span>
                  <span className="text-xs text-muted">{project.description ?? ''}</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </AppShell>
  );
}
