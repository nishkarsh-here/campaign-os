/**
 * Media URLs the API signs.
 *
 * A byte-serving path now carries a short-lived signature in its query string,
 * because an `<img src>` cannot send `Authorization` or `X-Organization-Id`.
 * Two rules follow, and both were broken once: pass the path through
 * untouched, and never build a variant by appending to it.
 */

import { describe, expect, it } from 'vitest';
import { mediaUrl } from './api';

const SIGNED =
  '/v1/campaigns/c-1/assets/a-1/content?token=eyJlIjoxNzAwMDAwMDAwfQ.c2lnbmF0dXJl';

describe('every media consumer resolves through mediaUrl', async () => {
  it('no component passes a raw API path to a src or href', async () => {
    // A relative `src` resolves against the *page* origin — the Next server,
    // which serves no bytes. The moodboard did exactly this and rendered a
    // broken image beside a perfectly good analysis of it.
    const { readdir, readFile } = await import('node:fs/promises');
    const dir = new URL('../components/', import.meta.url);
    const files = (await readdir(dir)).filter((f) => f.endsWith('.tsx') && !f.includes('.test.'));
    const offenders: string[] = [];
    for (const file of files) {
      const source = await readFile(new URL(file, dir), 'utf8');
      for (const match of source.matchAll(/(?:src|href)=\{([^}]*\burl\b[^}]*)\}/g)) {
        if (!match[1]!.includes('mediaUrl')) offenders.push(`${file}: ${match[1]!.trim()}`);
      }
    }
    expect(offenders).toEqual([]);
  });
});

describe('mediaUrl', () => {
  it('keeps the signature intact when it makes the path absolute', () => {
    const resolved = mediaUrl(SIGNED);
    expect(resolved.endsWith(SIGNED)).toBe(true);
    expect(resolved).toMatch(/^https?:\/\//);
  });

  it('does not touch a URL that is already absolute', () => {
    const absolute = `https://api.example.test${SIGNED}`;
    expect(mediaUrl(absolute)).toBe(absolute);
  });

  it('leaves exactly one query string, so the token is not swallowed', () => {
    // `url + '?download=true'` produced `…?token=X?download=true`, which made
    // the token value `X?download=true` and every download 404.
    expect(mediaUrl(SIGNED).split('?')).toHaveLength(2);
  });
});
