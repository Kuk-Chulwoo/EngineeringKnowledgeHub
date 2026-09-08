import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import GoldenEvaluation from './GoldenEvaluation';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const json = (value: unknown) => new Response(JSON.stringify(value));

it('requires explicit source curation and review before comparing, and renders every classification', async () => {
  const user = userEvent.setup();
  let golden: { id: number; status: string; manifest_sha256: string; manifest: unknown } | null = null;
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/revisions/7/golden-references')) return json(golden ? [golden] : []);
    if (url.endsWith('/golden-references') && init?.method === 'POST') {
      const body = JSON.parse(init.body as string);
      expect(body.manually_curated_from_source).toBe(true);
      golden = { id: 1, status: 'ENGINEER_DRAFT', manifest_sha256: 'hash', manifest: body.manifest };
      return json(golden);
    }
    if (url.endsWith('/approval')) { golden!.status = 'ENGINEER_APPROVED'; return json(golden); }
    if (url.endsWith('/evaluations/3')) return json({ unit: 'field claims', wrong_value_count: 1,
      missing_value_count: 1, invented_value_count: 1,
      metrics: { Identity: { match: 1, mismatch: 1, missing: 1, extra: 1, expected: 3, covered: 2, coverage: 2/3 } },
      rows: ['MATCH', 'MISMATCH', 'MISSING', 'EXTRA'].map(status => ({ category: 'Identity', entity: ['COMPONENT_IDENTITY'], field: 'manufacturer', status, golden: 'A', candidate: 'B' })) });
    throw new Error(url);
  });
  vi.stubGlobal('fetch', fetcher);
  render(<GoldenEvaluation revisionId="7" runId={3} csrf="csrf" />);
  await user.click(screen.getByText('Import manually curated golden reference'));
  expect(screen.getByRole('button', { name: 'Import golden draft' }).hasAttribute('disabled')).toBe(true);
  await user.type(screen.getByLabelText('Manually curated manifest JSON'), '{{"curation_notes":"manually checked"}');
  await user.click(screen.getByLabelText(/I manually curated/));
  await user.click(screen.getByRole('button', { name: 'Import golden draft' }));
  await screen.findByText('Golden 1 · ENGINEER_DRAFT');
  expect(screen.getByRole('button', { name: 'Compare original AI candidates' }).hasAttribute('disabled')).toBe(true);
  await user.click(screen.getByLabelText(/I reviewed this exact/));
  await user.click(screen.getByRole('button', { name: 'Approve golden reference' }));
  await screen.findByText('Golden 1 · ENGINEER_APPROVED');
  await user.click(screen.getByRole('button', { name: 'Compare original AI candidates' }));
  await screen.findByText('MISMATCH');
  for (const status of ['MATCH', 'MISSING', 'EXTRA']) expect(screen.getByText(status)).toBeTruthy();
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(2);
});
