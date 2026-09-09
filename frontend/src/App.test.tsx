import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const component = { id: 1, manufacturer: 'Acme', part_number: 'REF123', description: 'Reference',
  category: 'Analog', package: 'SOIC-8', internal_part_number: 'INT-1', lifecycle_status: 'DRAFT',
  created_at: '2026-09-08T00:00:00Z', updated_at: '2026-09-08T00:00:00Z' };
const revision = { id: 3, revision: 'A', filename: 'reference.pdf', datasheet_date: '2026-09-01',
  uploaded_at: '2026-09-08T00:00:00Z', size_bytes: 2048, sha256: 'abc' };
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

it('registers a component and opens the saved overview', async () => {
  const user = userEvent.setup();
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === 'POST') return json(component, 201);
    if (url === '/api/v1/components/1') return json({ ...component, documents: [], pin_summary: { count: 0, source_type: null } });
    return json({ items: [], total: 0, limit: 20, offset: 0 });
  });
  vi.stubGlobal('fetch', fetcher);
  render(<App />);
  await user.click(screen.getByRole('button', { name: '+ Register component' }));
  await user.type(screen.getByLabelText('Manufacturer', { exact: true }), 'Acme');
  await user.type(screen.getByLabelText('Manufacturer Part Number'), 'REF123');
  await user.click(screen.getByRole('button', { name: 'Save component' }));
  await screen.findByRole('heading', { name: 'REF123' });
  const call = fetcher.mock.calls.find(([, init]) => init?.method === 'POST')!;
  expect(JSON.parse(call[1]!.body as string).part_number).toBe('REF123');
  expect(screen.getByRole('button', { name: 'PCB Library' }).hasAttribute('disabled')).toBe(true);
});

it('uploads a PDF, refreshes revision history, and exposes view/download', async () => {
  const user = userEvent.setup();
  let uploaded = false;
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === 'POST') { uploaded = true; return json(revision, 201); }
    if (url === '/api/v1/components/1') return json({ ...component,
      pin_summary: { count: 0, source_type: null },
      documents: uploaded ? [{ id: 2, title: 'Datasheet', revisions: [revision] }] : [] });
    return json({ items: [component], total: 1, limit: 20, offset: 0 });
  });
  vi.stubGlobal('fetch', fetcher);
  render(<App />);
  await user.click(await screen.findByRole('button', { name: /Acme REF123/ }));
  await user.click(await screen.findByRole('button', { name: 'Manage documents' }));
  await user.type(screen.getByLabelText('Revision', { exact: true }), 'A');
  await user.upload(screen.getByLabelText('PDF file'), new File(['%PDF-test'], 'reference.pdf', { type: 'application/pdf' }));
  // jsdom does not connect user-event's FileList to native required-file validity.
  // Submit the form handler explicitly; real PDF transport is covered by backend tests.
  fireEvent.submit(screen.getByRole('button', { name: 'Upload PDF' }).closest('form')!);
  await screen.findByText('PDF stored. Previous revisions are preserved.');
  await user.click(await screen.findByRole('button', { name: 'View Datasheet A' }));
  expect(screen.getByTitle('PDF: reference.pdf').getAttribute('src')).toBe('/api/v1/revisions/3/file');
  expect(screen.getByRole('link', { name: 'Download' }).getAttribute('href'))
    .toBe('/api/v1/revisions/3/file?download=true');
  const data = fetcher.mock.calls.find(([, init]) => init?.method === 'POST')![1]!.body as FormData;
  expect(data.get('revision')).toBe('A');
  expect(data.has('datasheet_date')).toBe(false);
});

it('shows server errors without claiming registration succeeded', async () => {
  const user = userEvent.setup();
  vi.stubGlobal('fetch', vi.fn(async (_url: string, init?: RequestInit) =>
    init?.method === 'POST' ? json({ detail: 'Component already exists' }, 409) :
      json({ items: [], total: 0, limit: 20, offset: 0 })));
  render(<App />);
  await user.click(screen.getByRole('button', { name: '+ Register component' }));
  await user.type(screen.getByLabelText('Manufacturer', { exact: true }), 'Acme');
  await user.type(screen.getByLabelText('Manufacturer Part Number'), 'REF123');
  await user.click(screen.getByRole('button', { name: 'Save component' }));
  expect((await screen.findByRole('alert')).textContent).toContain('Component already exists');
  expect(screen.getByRole('button', { name: 'Save component' }).hasAttribute('disabled')).toBe(false);
});

it('sends the current search term to the catalog endpoint', async () => {
  const user = userEvent.setup();
  const fetcher = vi.fn(async () => json({ items: [], total: 0, limit: 20, offset: 0 }));
  vi.stubGlobal('fetch', fetcher);
  render(<App />);
  await user.type(screen.getByRole('searchbox'), 'voltage');
  await waitFor(() => expect(fetcher).toHaveBeenCalledWith(
    '/api/v1/components?q=voltage&limit=20&offset=0', expect.any(Object)));
  await screen.findByText('No matching components');
});

it('edits company metadata, transitions lifecycle, and views canonical pins', async () => {
  const user = userEvent.setup();
  const detail = { ...component, documents: [], pin_summary: { count: 1, source_type: 'MANUAL' } };
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/pins')) return json({ count: 1, source_type: 'MANUAL', pins: [{
      id: 9, component_id: 1, pin_number: 'A1', pin_name: 'VCC', source_type: 'MANUAL',
    }] });
    if (init?.method === 'PATCH' || url.endsWith('/lifecycle')) return json(detail);
    if (url === '/api/v1/components/1') return json(detail);
    return json({ items: [component], total: 1, limit: 20, offset: 0 });
  });
  vi.stubGlobal('fetch', fetcher);
  render(<App />);
  await user.click(await screen.findByRole('button', { name: /Acme REF123/ }));
  await user.click(await screen.findByRole('button', { name: 'Edit metadata' }));
  await user.clear(screen.getByLabelText('Internal Part Number'));
  await user.type(screen.getByLabelText('Internal Part Number'), 'INT-2');
  await user.click(screen.getByRole('button', { name: 'Save metadata' }));
  expect(fetcher.mock.calls.some(([, init]) => init?.method === 'PATCH')).toBe(true);
  await user.click(screen.getByRole('button', { name: 'VALIDATED' }));
  expect(fetcher.mock.calls.some(([url]) => url.endsWith('/lifecycle'))).toBe(true);
  await user.click(screen.getByRole('button', { name: 'View Pins' }));
  expect(await screen.findByText('VCC')).toBeTruthy();
});

it('previews and confirms USER_IMPORT only after replacement acknowledgement', async () => {
  const user = userEvent.setup();
  const detail = { ...component, documents: [], pin_summary: { count: 2, source_type: 'MANUAL' } };
  const preview = { filename: 'pins.xlsx', format: 'xlsx', valid: true, count: 2,
    errors: [], warnings: [], pins: [{ pin_number: '1', pin_name: 'RESET_N' },
      { pin_number: 'EP', pin_name: 'GND' }] };
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/pin-import/preview')) return json(preview);
    if (url.endsWith('/pins') && init?.method === 'PUT') return json({ ...preview,
      source_type: 'USER_IMPORT', pins: preview.pins.map((pin, index) => ({
        ...pin, id: index + 1, component_id: 1, source_type: 'USER_IMPORT',
      })) });
    if (url === '/api/v1/components/1') return json(detail);
    return json({ items: [component], total: 1, limit: 20, offset: 0 });
  });
  vi.stubGlobal('fetch', fetcher);
  render(<App />);
  await user.click(await screen.findByRole('button', { name: /Acme REF123/ }));
  expect(screen.getByRole('link', { name: 'Download CSV Template' }).getAttribute('href'))
    .toBe('/api/v1/pin-import/template?format=csv');
  await user.upload(screen.getByLabelText('Import Pin File'), new File(['xlsx'], 'pins.xlsx'));
  expect(await screen.findByText('Pin Import Preview')).toBeTruthy();
  expect(screen.getByText(/will replace the current Pin Table \(2 pins\)/)).toBeTruthy();
  const importButton = screen.getByRole('button', { name: 'Import Pins' });
  expect(importButton.hasAttribute('disabled')).toBe(true);
  await user.click(screen.getByRole('checkbox'));
  await user.click(importButton);
  await screen.findByText('Pin table imported.');
  const call = fetcher.mock.calls.find(([url, init]) => url.endsWith('/pins') && init?.method === 'PUT')!;
  expect(JSON.parse(call[1]!.body as string)).toEqual({ source_type: 'USER_IMPORT', pins: preview.pins });
});

it('shows preview validation errors and disables import', async () => {
  const user = userEvent.setup();
  const detail = { ...component, documents: [], pin_summary: { count: 0, source_type: null } };
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url.endsWith('/pin-import/preview')) return json({ filename: 'bad.csv', format: 'csv',
      valid: false, count: 0, warnings: [], pins: [], errors: [{ code: 'DUPLICATE_PIN_NUMBER',
        row: 14, field: 'pin_number', message: 'Duplicate pin number' }] });
    if (url === '/api/v1/components/1') return json(detail);
    return json({ items: [component], total: 1, limit: 20, offset: 0 });
  }));
  render(<App />);
  await user.click(await screen.findByRole('button', { name: /Acme REF123/ }));
  await user.upload(screen.getByLabelText('Import Pin File'), new File(['bad'], 'bad.csv'));
  expect(await screen.findByText('Duplicate pin number')).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Import Pins' }).hasAttribute('disabled')).toBe(true);
});

it('registers an existing symbol, uploads its source, reviews pins, and advances lifecycle', async () => {
  const user = userEvent.setup();
  const detail = { ...component, documents: [], pin_summary: { count: 1, source_type: 'MANUAL' } };
  let symbols: Array<Record<string, unknown>> = [];
  const baseSymbol = { id: 10, component_id: 1, cad_tool: 'PADS_LOGIC', cad_version: 'VX2.11',
    symbol_name: 'CC1120', source_type: 'EXISTING_COMPANY_LIBRARY', source_filename: null,
    revision: 'A', lifecycle_status: 'DRAFT', pin_validation_status: 'NOT_CHECKED', notes: '',
    size_bytes: null, sha256: null, created_at: '', updated_at: '' };
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/components/1/symbols') && init?.method === 'POST') {
      symbols = [{ ...baseSymbol }]; return json(symbols[0], 201);
    }
    if (url.endsWith('/symbols/10/file') && init?.method === 'POST') {
      symbols[0] = { ...symbols[0], source_filename: 'CC1120.c', size_bytes: 3, sha256: 'abc' };
      return json(symbols[0]);
    }
    if (url.endsWith('/pin-validation')) {
      symbols[0] = { ...symbols[0], pin_validation_status: 'ENGINEER_REVIEWED' }; return json(symbols[0]);
    }
    if (url.endsWith('/lifecycle')) {
      symbols[0] = { ...symbols[0], lifecycle_status: 'VALIDATED' }; return json(symbols[0]);
    }
    if (url.endsWith('/components/1/symbols')) return json(symbols);
    if (url === '/api/v1/components/1') return json(detail);
    return json({ items: [component], total: 1, limit: 20, offset: 0 });
  });
  vi.stubGlobal('fetch', fetcher);
  render(<App />);
  await user.click(await screen.findByRole('button', { name: /Acme REF123/ }));
  const section = await screen.findByRole('region', { name: 'Schematic Symbol' });
  expect(within(section).getByText('No schematic symbol registered.')).toBeTruthy();
  await user.click(within(section).getByRole('button', { name: 'Register Existing Symbol' }));
  await user.type(within(section).getByLabelText('Symbol Name'), 'CC1120');
  await user.type(within(section).getByLabelText('Revision'), 'A');
  await user.upload(within(section).getByLabelText('Symbol File'), new File(['CAE'], 'CC1120.c'));
  fireEvent.submit(within(section).getByRole('button', { name: 'Register' }).closest('form')!);
  await within(section).findByText('CC1120.c');
  expect(within(section).getByText(/PADS Logic/)).toBeTruthy();
  await user.click(within(section).getByRole('button', { name: 'Mark Pins Engineer Reviewed' }));
  await within(section).findByText('ENGINEER_REVIEWED');
  await user.click(within(section).getByRole('button', { name: 'VALIDATED' }));
  await within(section).findByText('VALIDATED', { selector: '.badge' });
  expect(screen.queryByText('PCB Footprint')).toBeNull();
});
