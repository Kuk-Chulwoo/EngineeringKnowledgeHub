import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import EngineeringPanel from './EngineeringPanel';
import type { Detail } from './api';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const detail: Detail = {
  id: 1, manufacturer: 'Fabricated', part_number: 'SYNTH-DEMO', description: 'Test',
  category: 'Test', package: 'Test', created_at: '2026-09-08T00:00:00Z',
  updated_at: '2026-09-08T00:00:00Z', internal_part_number: null, lifecycle_status: 'DRAFT',
  pin_summary: { count: 0, source_type: null },
  documents: [{ id: 1, title: 'Synthetic', revisions: [{ id: 7, revision: 'TEST',
    filename: 'fabricated.pdf', datasheet_date: null, uploaded_at: '2026-09-08T00:00:00Z',
    size_bytes: 1234, sha256: 'abc' }] }],
};
function completed() {
  return { id: 3, status: 'SUCCEEDED', source_revision_id: 7, source_sha256: 'abc',
    provenance: { pipeline_version: 'synthetic/1', model_identifier: 'none-synthetic' },
    error_code: null, error_summary: null, candidate_set_sha256: 'hash', created_at: '',
    entities: [{ id: 4, local_key: 'pkg', kind: 'PACKAGE', fields: [{
      id: 10, key: 'family', value: 'TEST-QFN', availability: 'PRESENT', confidence: null,
      confidence_basis: 'NOT_PROVIDED', review_status: 'AI_EXTRACTED', latest_review_sequence: 1,
      source_revision_id: 7, origin: 'AI', content_sha256: 'field-hash', supersedes_field_id: null,
      evidence: [{ source_revision_id: 7, page_number: 1, source_text: 'Fabricated package TEST-QFN',
        locator_method: 'TEXT', printed_page_label: null }],
      history: [{ sequence: 1, status: 'AI_EXTRACTED', actor_id: 'synthetic-worker',
        reason: 'Initial candidate', created_at: '2026-09-08T00:00:00Z' }],
    }] }],
  };
}
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });

it('starts a synthetic run and submits an explicit engineer review with CSRF and sequence', async () => {
  const user = userEvent.setup();
  const run = completed();
  let started = false;
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/reviewer/session')) return json({ actor: 'Engineer', csrf_token: 'test-csrf' });
    if (url.endsWith('/extraction-runs') && init?.method === 'POST') {
      started = true; return json({ ...run, status: 'QUEUED', entities: [] }, 201);
    }
    if (url.endsWith('/extraction-runs')) return json(started ? [run] : []);
    if (url.endsWith('/reviews')) {
      run.entities[0].fields[0].review_status = 'ENGINEER_APPROVED';
      run.entities[0].fields[0].latest_review_sequence = 2;
      return json({ status: 'ENGINEER_APPROVED' }, 201);
    }
    if (url.endsWith('/extraction-runs/3')) return json(run);
    throw new Error('Unexpected endpoint: ' + url);
  });
  vi.stubGlobal('fetch', fetcher);
  render(<EngineeringPanel detail={detail} />);
  await screen.findByText('Engineer', { exact: true });
  await user.selectOptions(screen.getByLabelText('Source document revision'), '7');
  await user.click(screen.getByRole('button', { name: 'Start synthetic extraction' }));
  await screen.findByText('Run 3: SUCCEEDED');
  await user.click(screen.getByText('pkg · PACKAGE · 1 field versions'));
  expect(screen.getByText('AI_EXTRACTED', { selector: '.badge' })).toBeTruthy();
  expect(screen.getByText(/Confidence: Not provided/)).toBeTruthy();
  expect(screen.getByRole('link', { name: /Source revision 7, PDF page 1/ }).getAttribute('href'))
    .toBe('/api/v1/revisions/7/file#page=1');
  await user.type(screen.getByLabelText('Review reason for family'), 'Checked synthetic source');
  await user.click(screen.getByRole('button', { name: 'Approve field' }));
  await screen.findByText('ENGINEER_APPROVED', { selector: '.badge' });
  const call = fetcher.mock.calls.find(([url]) => url.endsWith('/reviews'))!;
  expect(JSON.parse(call[1]!.body as string)).toEqual({
    status: 'ENGINEER_APPROVED', expected_sequence: 1, reason: 'Checked synthetic source',
  });
  expect((call[1]!.headers as Record<string, string>)['X-CSRF-Token']).toBe('test-csrf');
});

it('requires reviewer sign-in and preserves an error from the server', async () => {
  const user = userEvent.setup();
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) =>
    url.endsWith('/reviewer/session') ?
      json({ detail: init?.method === 'POST' ? 'Invalid reviewer credentials' : 'Sign in' }, 401) : json([])));
  render(<EngineeringPanel detail={detail} />);
  await user.selectOptions(screen.getByLabelText('Source document revision'), '7');
  expect(screen.getByRole('button', { name: 'Start synthetic extraction' }).hasAttribute('disabled')).toBe(true);
  await user.type(screen.getByLabelText('Engineer name'), 'Engineer');
  await user.type(screen.getByLabelText('Engineer password'), 'incorrect-password');
  await user.click(screen.getByRole('button', { name: 'Sign in for review' }));
  await screen.findByRole('alert');
  expect(screen.getByRole('alert').textContent).toBe('Invalid reviewer credentials');
});

it('does not turn a stale rejected review request into an approval', async () => {
  const user = userEvent.setup();
  const run = completed();
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/reviewer/session')) return json({ actor: 'Engineer', csrf_token: 'csrf' });
    if (url.endsWith('/reviews')) return json({ detail: 'Stale review sequence' }, 409);
    if (url.endsWith('/extraction-runs')) return json([run]);
    return json(run);
  }));
  render(<EngineeringPanel detail={detail} />);
  await screen.findByText('Engineer', { exact: true });
  await user.selectOptions(screen.getByLabelText('Source document revision'), '7');
  await waitFor(() => expect(screen.getByRole('option', { name: 'Run 3 · SUCCEEDED' })).toBeTruthy());
  await user.selectOptions(screen.getByLabelText('Extraction run'), '3');
  await screen.findByText('Run 3: SUCCEEDED');
  await user.click(screen.getByText('pkg · PACKAGE · 1 field versions'));
  await user.type(screen.getByLabelText('Review reason for family'), 'Reviewed');
  await user.click(screen.getByRole('button', { name: 'Reject field' }));
  expect((await screen.findByRole('alert')).textContent).toBe('Stale review sequence');
  expect(screen.getByText('AI_EXTRACTED', { selector: '.badge' })).toBeTruthy();
});


it('gates real AI extraction on configured provider, package scope and explicit transmission consent', async () => {
  const user = userEvent.setup();
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/reviewer/session')) return json({ actor: 'Engineer', csrf_token: 'csrf' });
    if (url.endsWith('/provider-config')) return json({ provider: 'openai', model: 'mock-model', enabled: true, configured: true });
    if (url.endsWith('/extraction-runs') && init?.method === 'POST') return json({ ...completed(), status: 'QUEUED', entities: [] });
    if (url.endsWith('/extraction-runs')) return json([]);
    if (url.endsWith('/extraction-runs/3')) return json(completed());
    if (url.endsWith('/golden-references')) return json([]);
    throw new Error(url);
  });
  vi.stubGlobal('fetch', fetcher);
  render(<EngineeringPanel detail={detail} />);
  await screen.findByText('Engineer', { exact: true });
  await user.selectOptions(screen.getByLabelText('Source document revision'), '7');
  await user.selectOptions(screen.getByLabelText('Extraction mode'), 'openai');
  expect(screen.getByRole('button', { name: 'Start Real AI Extraction' }).hasAttribute('disabled')).toBe(true);
  await user.type(screen.getByLabelText('Package scope'), 'Reviewed package scope');
  await user.click(screen.getByLabelText(/I authorize sending/));
  await user.click(screen.getByRole('button', { name: 'Start Real AI Extraction' }));
  const post = fetcher.mock.calls.find(([url, init]) => url.endsWith('/extraction-runs') && init?.method === 'POST')!;
  expect(JSON.parse(post[1]!.body as string)).toEqual({ provider: 'openai', retry_of_run_id: null,
    external_transmission_authorized: true, settings: { package_scope: 'Reviewed package scope' } });
});
