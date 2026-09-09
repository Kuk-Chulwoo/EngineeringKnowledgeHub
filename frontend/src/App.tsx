import { useEffect, useState, type ChangeEvent, type FormEvent } from 'react';
import { api, fileUrl, symbolFileUrl, type Component, type Detail, type PinImportPreview,
  type PinTable, type Revision, type SchematicSymbol, type SearchResult } from './api';
import { componentTabs } from './modules';
import EngineeringPanel from './EngineeringPanel';
import './engineering.css';

const message = (error: unknown) => error instanceof Error ? error.message : 'Unexpected error';
const time = (value: string) => new Date(value).toLocaleString();

function Register({ onSaved, onCancel }: { onSaved: (value: Component) => void; onCancel: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget));
    if (!values.internal_part_number) delete values.internal_part_number;
    setBusy(true); setError('');
    try {
      onSaved(await api<Component>('/components', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(values),
      }));
    } catch (error) { setError(message(error)); } finally { setBusy(false); }
  }
  return <section className="panel registration" aria-labelledby="register-title">
    <div className="section-heading"><h2 id="register-title">Register component</h2>
      <button className="quiet" onClick={onCancel} disabled={busy}>Cancel</button></div>
    <form onSubmit={submit}>
      <div className="fields">
        <label>Manufacturer<input name="manufacturer" required maxLength={200} autoFocus /></label>
        <label>Manufacturer Part Number<input name="part_number" required maxLength={200} /></label>
        <label>Internal Part Number<input name="internal_part_number" maxLength={200} /></label>
        <label>Category<input name="category" maxLength={200} placeholder="e.g. Power management" /></label>
        <label>Package<input name="package" maxLength={200} placeholder="e.g. SOIC-8" /></label>
        <label className="wide">Description<textarea name="description" maxLength={4000} rows={3} /></label>
      </div>
      {error && <p role="alert" className="error">{error}</p>}
      <button type="submit" disabled={busy}>{busy ? 'Saving…' : 'Save component'}</button>
    </form>
  </section>;
}

function Upload({ detail, onSaved }: { detail: Detail; onSaved: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    if (!data.get('datasheet_date')) data.delete('datasheet_date');
    setBusy(true); setError(''); setSuccess('');
    try {
      await api(`/components/${detail.id}/revisions`, { method: 'POST', body: data });
      form.reset(); setSuccess('PDF stored. Previous revisions are preserved.'); onSaved();
    } catch (error) { setError(message(error)); } finally { setBusy(false); }
  }
  return <section className="upload-section" aria-labelledby="upload-title">
    <h3 id="upload-title">Upload document revision</h3>
    <p className="muted">Reuse a document title to add a revision, or enter a new title for another document.</p>
    <form onSubmit={submit}>
      <fieldset disabled={busy}>
        <div className="fields">
          <label>Document title<input name="document_title" defaultValue="Datasheet" list="document-titles" required maxLength={200} /></label>
          <datalist id="document-titles">{detail.documents.map(d => <option key={d.id} value={d.title} />)}</datalist>
          <label>Revision<input name="revision" required maxLength={200} placeholder="e.g. Rev. A" /></label>
          <label>Datasheet date (optional)<input name="datasheet_date" type="date" /></label>
          <label>PDF file<input name="file" type="file" accept=".pdf,application/pdf" required /></label>
        </div>
        <button type="submit">{busy ? 'Uploading…' : 'Upload PDF'}</button>
      </fieldset>
      {error && <p role="alert" className="error">{error}</p>}
      {success && <p role="status" className="success">{success}</p>}
    </form>
  </section>;
}

function SymbolSection({ componentId, pinCount, symbols, onChanged }: {
  componentId: number; pinCount: number; symbols: SchematicSymbol[]; onChanged: () => void;
}) {
  const [registering, setRegistering] = useState(false);
  const [editing, setEditing] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const transitions: Record<Component['lifecycle_status'], Component['lifecycle_status'][]> = {
    DRAFT: ['VALIDATED'], VALIDATED: ['DRAFT', 'ENGINEER_APPROVED'],
    ENGINEER_APPROVED: ['VALIDATED', 'RELEASED'], RELEASED: ['ENGINEER_APPROVED'],
  };
  async function register(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError('');
    const form = event.currentTarget; const data = new FormData(form);
    const file = data.get('file') as File;
    const body = Object.fromEntries(['cad_tool', 'cad_version', 'symbol_name', 'source_type',
      'revision', 'notes'].map(key => [key, data.get(key)]));
    try {
      const created = await api<SchematicSymbol>(`/components/${componentId}/symbols`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      });
      const upload = new FormData(); upload.append('file', file);
      await api(`/symbols/${created.id}/file`, { method: 'POST', body: upload });
      setRegistering(false); onChanged();
    } catch (error) { setError(message(error)); }
    finally { setBusy(false); }
  }
  async function upload(symbolId: number, file: File) {
    const data = new FormData(); data.append('file', file); setBusy(true); setError('');
    try { await api(`/symbols/${symbolId}/file`, { method: 'POST', body: data }); onChanged(); }
    catch (error) { setError(message(error)); } finally { setBusy(false); }
  }
  async function update(event: FormEvent<HTMLFormElement>, symbolId: number) {
    event.preventDefault(); setBusy(true); setError('');
    try {
      await api(`/symbols/${symbolId}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(Object.fromEntries(new FormData(event.currentTarget))) });
      setEditing(null); onChanged();
    } catch (error) { setError(message(error)); } finally { setBusy(false); }
  }
  async function action(symbolId: number, path: string, status: string) {
    setBusy(true); setError('');
    try { await api(`/symbols/${symbolId}/${path}`, { method: 'POST',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status }) }); onChanged(); }
    catch (error) { setError(message(error)); } finally { setBusy(false); }
  }
  return <section className="overview-action" aria-labelledby="symbols-title">
    <div className="section-heading"><div><h3 id="symbols-title">Schematic Symbol</h3>
      <p className="muted">Canonical pins: {pinCount}</p></div>
      {!registering && <button onClick={() => setRegistering(true)}>Register Existing Symbol</button>}</div>
    {error && <p role="alert" className="error">{error}</p>}
    {registering && <form onSubmit={register}><fieldset disabled={busy}><div className="fields">
      <label>CAD Tool<select name="cad_tool" defaultValue="PADS_LOGIC"><option value="PADS_LOGIC">PADS Logic</option></select></label>
      <label>Version<input name="cad_version" required defaultValue="VX2.11" /></label>
      <label>Symbol Name<input name="symbol_name" required /></label>
      <label>Source Type<select name="source_type" defaultValue="EXISTING_COMPANY_LIBRARY">
        <option value="EXISTING_COMPANY_LIBRARY">Existing Company Library</option>
        <option value="MANUFACTURER_LIBRARY">Manufacturer Library</option>
        <option value="ENGINEER_CREATED">Engineer Created</option>
        <option value="IMPORTED_VENDOR_LIBRARY">Imported Vendor Library</option></select></label>
      <label>Revision<input name="revision" required /></label>
      <label>Symbol File<input name="file" type="file" accept=".c" required /></label>
      <label className="wide">Notes<textarea name="notes" rows={2} /></label>
    </div><div className="actions"><button className="quiet" type="button" onClick={() => setRegistering(false)}>Cancel</button>
      <button type="submit">Register</button></div></fieldset></form>}
    {symbols.length === 0 && !registering && <p>No schematic symbol registered.</p>}
    {symbols.map(symbol => <article className="symbol-card" key={symbol.id}>
      <div className="section-heading"><h4>{symbol.symbol_name}</h4><span className="badge">{symbol.lifecycle_status}</span></div>
      {editing === symbol.id ? <form onSubmit={event => update(event, symbol.id)}><div className="fields">
        <label>Version<input name="cad_version" required defaultValue={symbol.cad_version} /></label>
        <label>Symbol Name<input name="symbol_name" required defaultValue={symbol.symbol_name} /></label>
        <label>Source Type<select name="source_type" defaultValue={symbol.source_type}>
          <option value="EXISTING_COMPANY_LIBRARY">Existing Company Library</option>
          <option value="MANUFACTURER_LIBRARY">Manufacturer Library</option><option value="ENGINEER_CREATED">Engineer Created</option>
          <option value="IMPORTED_VENDOR_LIBRARY">Imported Vendor Library</option></select></label>
        <label>Revision<input name="revision" required defaultValue={symbol.revision} /></label>
        <label className="wide">Notes<textarea name="notes" defaultValue={symbol.notes} /></label>
      </div><button type="submit" disabled={busy}>Save Symbol</button></form> : <dl className="facts">
        <div><dt>CAD Tool / Version</dt><dd>PADS Logic · {symbol.cad_version}</dd></div>
        <div><dt>Source</dt><dd>{symbol.source_type}</dd></div><div><dt>Revision</dt><dd>{symbol.revision}</dd></div>
        <div><dt>Pin Review</dt><dd>{symbol.pin_validation_status}</dd></div>
        <div><dt>File</dt><dd>{symbol.source_filename || 'Not attached'}</dd></div>
      </dl>}
      <div className="actions"><button className="quiet" onClick={() => setEditing(symbol.id)}>Edit</button>
        {symbol.source_filename ? <a className="button-link" href={symbolFileUrl(symbol.id, true)}>Download</a>
          : <label className="button-link">Attach Source File<input className="visually-hidden" type="file" accept=".c"
            onChange={event => { const file = event.target.files?.[0]; if (file) upload(symbol.id, file); }} /></label>}
        {symbol.pin_validation_status === 'NOT_CHECKED' && <button disabled={busy}
          onClick={() => action(symbol.id, 'pin-validation', 'ENGINEER_REVIEWED')}>Mark Pins Engineer Reviewed</button>}
        {transitions[symbol.lifecycle_status].map(status => <button disabled={busy} key={status}
          onClick={() => action(symbol.id, 'lifecycle', status)}>{status}</button>)}</div>
    </article>)}
  </section>;
}

function ComponentPage({ id }: { id: number }) {
  const [detail, setDetail] = useState<Detail | null>(null);
  const [tab, setTab] = useState('overview');
  const [refresh, setRefresh] = useState(0);
  const [error, setError] = useState('');
  const [viewing, setViewing] = useState<Revision | null>(null);
  const [editing, setEditing] = useState(false);
  const [pins, setPins] = useState<PinTable | null>(null);
  const [pinPreview, setPinPreview] = useState<PinImportPreview | null>(null);
  const [pinImportBusy, setPinImportBusy] = useState(false);
  const [replaceConfirmed, setReplaceConfirmed] = useState(false);
  const [pinImportStatus, setPinImportStatus] = useState('');
  const [symbols, setSymbols] = useState<SchematicSymbol[]>([]);
  useEffect(() => {
    const controller = new AbortController();
    setError('');
    api<Detail>(`/components/${id}`, { signal: controller.signal })
      .then(setDetail).catch(error => { if (!controller.signal.aborted) setError(message(error)); });
    return () => controller.abort();
  }, [id, refresh]);
  useEffect(() => {
    const controller = new AbortController();
    api<unknown>(`/components/${id}/symbols`, { signal: controller.signal })
      .then(value => setSymbols(Array.isArray(value) ? value as SchematicSymbol[] : []))
      .catch(error => { if (!controller.signal.aborted) setError(message(error)); });
    return () => controller.abort();
  }, [id, refresh]);
  if (!detail) return <section className="panel"><p role={error ? 'alert' : 'status'}>{error || 'Loading component…'}</p>
    {error && <button onClick={() => setRefresh(n => n + 1)}>Retry</button>}</section>;
  const count = detail.documents.reduce((total, document) => total + document.revisions.length, 0);
  const currentPinCount = detail.pin_summary.count;
  const transitions: Record<Component['lifecycle_status'], Component['lifecycle_status'][]> = {
    DRAFT: ['VALIDATED'], VALIDATED: ['DRAFT', 'ENGINEER_APPROVED'],
    ENGINEER_APPROVED: ['VALIDATED', 'RELEASED'], RELEASED: ['ENGINEER_APPROVED'],
  };
  async function saveMetadata(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError('');
    try {
      const values: Record<string, FormDataEntryValue | null> =
        Object.fromEntries(new FormData(event.currentTarget));
      if (!values.internal_part_number) values.internal_part_number = null;
      await api(`/components/${id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(values) });
      setEditing(false); setRefresh(n => n + 1);
    } catch (error) { setError(message(error)); }
  }
  async function transition(status: Component['lifecycle_status']) {
    setError('');
    try {
      await api(`/components/${id}/lifecycle`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status }) }); setRefresh(n => n + 1);
    } catch (error) { setError(message(error)); }
  }
  async function viewPins() {
    try { setPins(await api<PinTable>(`/components/${id}/pins`)); }
    catch (error) { setError(message(error)); }
  }
  async function previewPinFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    const data = new FormData(); data.append('file', file);
    setPinImportBusy(true); setError(''); setPinImportStatus(''); setReplaceConfirmed(false);
    try { setPinPreview(await api<PinImportPreview>(`/components/${id}/pin-import/preview`, {
      method: 'POST', body: data,
    })); } catch (error) { setError(message(error)); setPinPreview(null); }
    finally { setPinImportBusy(false); event.target.value = ''; }
  }
  async function importPins() {
    if (!pinPreview?.valid || (currentPinCount > 0 && !replaceConfirmed)) return;
    setPinImportBusy(true); setError('');
    try {
      const imported = await api<PinTable>(`/components/${id}/pins`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source_type: 'USER_IMPORT', pins: pinPreview.pins }),
      });
      setPins(imported); setPinPreview(null); setPinImportStatus('Pin table imported.');
      setRefresh(n => n + 1);
    } catch (error) { setError(message(error)); }
    finally { setPinImportBusy(false); }
  }
  return <article className="panel detail">
    <header className="component-heading"><div><p className="eyebrow">{detail.manufacturer}</p>
      <h2>{detail.part_number}</h2><p>{detail.internal_part_number || 'No internal part number'}</p></div>
      <span className="badge">{detail.lifecycle_status}</span></header>
    <p className="description">{detail.description || 'No description provided.'}</p>
    <nav className="tabs" aria-label="Component sections">
      {componentTabs.map(item => <button key={item.id} className={tab === item.id ? 'active' : ''}
        disabled={!item.enabled} title={item.enabled ? undefined : 'Planned for a future version'}
        aria-current={tab === item.id ? 'page' : undefined} onClick={() => setTab(item.id)}>{item.label}</button>)}
    </nav>
    {error && <p className="error" role="alert">{error} <button onClick={() => setRefresh(n => n + 1)}>Retry</button></p>}
    {tab === 'engineering' ? <EngineeringPanel detail={detail} /> : tab === 'overview' ? <>
      <div className="actions"><button className="quiet" onClick={() => setEditing(value => !value)}>Edit metadata</button>
        {transitions[detail.lifecycle_status].map(status => <button key={status} onClick={() => transition(status)}>{status}</button>)}</div>
      {editing && <form onSubmit={saveMetadata}><div className="fields">
        <label>Internal Part Number<input name="internal_part_number" defaultValue={detail.internal_part_number || ''} /></label>
        <label>Manufacturer<input name="manufacturer" required defaultValue={detail.manufacturer} /></label>
        <label>Manufacturer Part Number<input name="part_number" required defaultValue={detail.part_number} /></label>
        <label>Category<input name="category" defaultValue={detail.category} /></label>
        <label>Package<input name="package" defaultValue={detail.package} /></label>
        <label className="wide">Description<textarea name="description" defaultValue={detail.description} /></label>
      </div><button type="submit">Save metadata</button></form>}
      <dl className="facts">
        <div><dt>Manufacturer</dt><dd>{detail.manufacturer}</dd></div>
        <div><dt>Part Number</dt><dd>{detail.part_number}</dd></div>
        <div><dt>Category</dt><dd>{detail.category || '—'}</dd></div>
        <div><dt>Package</dt><dd>{detail.package || '—'}</dd></div>
        <div><dt>Internal Part Number</dt><dd>{detail.internal_part_number || '—'}</dd></div>
        <div><dt>Lifecycle</dt><dd>{detail.lifecycle_status}</dd></div>
        <div><dt>Pins</dt><dd>{currentPinCount} · {detail.pin_summary.source_type || 'No source'}</dd></div>
        <div><dt>Registered</dt><dd>{time(detail.created_at)}</dd></div>
        <div><dt>Documents</dt><dd>{detail.documents.length} documents · {count} revisions</dd></div>
      </dl>
      <div className="overview-action"><h3>Canonical pin table</h3>
        <p className="muted">{currentPinCount} pins available for this company part.</p>
        <div className="actions"><button onClick={viewPins}>View Pins</button>
          <a className="button-link" href="/api/v1/pin-import/template?format=csv">Download CSV Template</a>
          <a className="button-link" href="/api/v1/pin-import/template?format=xlsx">Download XLSX Template</a>
          <label className="button-link">Import Pin File<input className="visually-hidden" type="file"
            accept=".csv,.xlsx" onChange={previewPinFile} disabled={pinImportBusy} /></label></div>
        {pinImportStatus && <p role="status" className="success">{pinImportStatus}</p>}
      </div>
      {pins && <div className="table-scroll"><table><thead><tr><th>Pin Number</th><th>Pin Name</th></tr></thead>
        <tbody>{pins.pins.map(pin => <tr key={pin.id}><td>{pin.pin_number}</td><td>{pin.pin_name}</td></tr>)}</tbody></table></div>}
      {pinPreview && <section className="overview-action" aria-labelledby="pin-preview-title">
        <h3 id="pin-preview-title">Pin Import Preview</h3>
        <p><strong>File:</strong> {pinPreview.filename}</p><p><strong>Detected Pins:</strong> {pinPreview.count}</p>
        <p><strong>Validation:</strong> <span className="badge">{pinPreview.valid ? 'VALID' : 'ERROR'}</span></p>
        {pinPreview.valid ? <div className="table-scroll"><table><thead><tr><th>Pin Number</th><th>Pin Name</th></tr></thead>
          <tbody>{pinPreview.pins.map(pin => <tr key={pin.pin_number}><td>{pin.pin_number}</td><td>{pin.pin_name}</td></tr>)}</tbody></table></div>
          : <div className="table-scroll"><table><thead><tr><th>Row</th><th>Field</th><th>Error</th></tr></thead>
            <tbody>{pinPreview.errors.map((issue, index) => <tr key={`${issue.code}-${index}`}>
              <td>{issue.row ?? '—'}</td><td>{issue.field ?? 'File'}</td><td>{issue.message}</td></tr>)}</tbody></table></div>}
        {pinPreview.valid && currentPinCount > 0 && <label className="replacement-confirm">
          <input type="checkbox" checked={replaceConfirmed} onChange={event => setReplaceConfirmed(event.target.checked)} />
          Importing {pinPreview.count} pins will replace the current Pin Table ({currentPinCount} pins).
        </label>}
        <div className="actions"><button className="quiet" onClick={() => setPinPreview(null)}>Cancel</button>
          <button onClick={importPins} disabled={pinImportBusy || !pinPreview.valid ||
            (currentPinCount > 0 && !replaceConfirmed)}>Import Pins</button></div>
      </section>}
      <SymbolSection componentId={id} pinCount={currentPinCount} symbols={symbols}
        onChanged={() => setRefresh(n => n + 1)} />
      <div className="overview-action"><h3>Datasheets & reference documents</h3>
        <p className="muted">Keep original PDFs and their revision history with this component.</p>
        <button onClick={() => setTab('documents')}>Manage documents</button></div>
    </> : <>
      <div className="section-heading"><h3>Document history</h3><span className="muted">{count} revisions</span></div>
      {detail.documents.length === 0 && <div className="empty compact"><h3>No documents yet</h3><p>Upload the first PDF below.</p></div>}
      {detail.documents.map(document => <section className="document" key={document.id}>
        <h4>{document.title}</h4>
        <div className="table-scroll"><table><thead><tr>
          <th>Revision / file</th><th>Datasheet date</th><th>Uploaded</th><th>Actions</th>
        </tr></thead><tbody>{document.revisions.map(revision => <tr key={revision.id}>
          <td><strong>{revision.revision}</strong><small>{revision.filename}</small>
            <small>{(revision.size_bytes / 1024).toFixed(1)} KB</small></td>
          <td>{revision.datasheet_date || 'Not specified'}</td><td>{time(revision.uploaded_at)}</td>
          <td><div className="actions"><button className="quiet" onClick={() => setViewing(revision)}
            aria-label={`View ${document.title} ${revision.revision}`}>View</button>
            <a className="button-link" href={fileUrl(revision.id, true)}>Download</a></div></td>
        </tr>)}</tbody></table></div>
      </section>)}
      {viewing && <section className="viewer" aria-label="PDF viewer"><div className="section-heading">
        <h3>{viewing.filename} · {viewing.revision}</h3><button className="quiet" onClick={() => setViewing(null)}>Close viewer</button></div>
        <p><a href={fileUrl(viewing.id)} target="_blank" rel="noreferrer">Open PDF in a new tab</a> · <a href={fileUrl(viewing.id, true)}>Download original</a></p>
        <iframe title={`PDF: ${viewing.filename}`} src={fileUrl(viewing.id)} />
      </section>}
      <Upload detail={detail} onSaved={() => setRefresh(n => n + 1)} />
    </>}
  </article>;
}

export default function App() {
  const [query, setQuery] = useState('');
  const [offset, setOffset] = useState(0);
  const [result, setResult] = useState<SearchResult | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [registering, setRegistering] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError('');
    const timer = setTimeout(() => {
      api<SearchResult>(`/components?q=${encodeURIComponent(query)}&limit=20&offset=${offset}`,
        { signal: controller.signal }).then(setResult)
        .catch(error => { if (!controller.signal.aborted) setError(message(error)); })
        .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    }, 200);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [query, offset, refresh]);
  return <div className="app">
    <header className="topbar"><div className="brand-mark" aria-hidden="true">EK</div>
      <div><h1>Engineering Knowledge Hub</h1><p>Component workspace</p></div><span className="version">v0.1</span></header>
    <main>
      <div className="workspace-heading"><div><p className="eyebrow">ENGINEERING CATALOG</p><h2>Components</h2></div>
        <button onClick={() => setRegistering(true)}>+ Register component</button></div>
      <div className="workspace">
        <aside className="panel catalog" aria-label="Component catalog">
          <label className="search-label">Search components<input type="search" value={query}
            onChange={event => { setQuery(event.target.value); setOffset(0); }}
            placeholder="Manufacturer, part number, description…" maxLength={200} /></label>
          <div className="catalog-status" role="status">{loading ? 'Searching…' : `${result?.total ?? 0} components`}</div>
          {error && <p className="error" role="alert">{error}<button className="quiet" onClick={() => setRefresh(n => n + 1)}>Retry</button></p>}
          {!loading && !error && result?.items.length === 0 && <div className="empty compact"><h3>{query ? 'No matching components' : 'Your catalog starts here'}</h3>
            <p>{query ? 'Try another part number or manufacturer.' : 'Register a component to organize its datasheets.'}</p></div>}
          <div className="component-list">{!error && result?.items.map(component => <button key={component.id}
            className={selected === component.id && !registering ? 'component-card selected' : 'component-card'}
            onClick={() => { setSelected(component.id); setRegistering(false); }}>
            <span className="maker">{component.manufacturer}</span><strong>{component.part_number}</strong>
            <span className="summary">{component.description || 'No description'}</span>
            <span className="card-meta">{component.category || 'Uncategorized'}<span>{component.package}</span></span>
          </button>)}</div>
          {result && result.total > 20 && <div className="pagination"><button className="quiet" disabled={loading || offset === 0}
            onClick={() => setOffset(n => Math.max(0, n - 20))}>Previous</button>
            <span>{Math.floor(offset / 20) + 1} / {Math.ceil(result.total / 20)}</span>
            <button className="quiet" disabled={loading || offset + 20 >= result.total} onClick={() => setOffset(n => n + 20)}>Next</button></div>}
        </aside>
        <div className="main-panel">{registering ? <Register onCancel={() => setRegistering(false)}
          onSaved={component => { setSelected(component.id); setRegistering(false); setQuery(''); setOffset(0); setRefresh(n => n + 1); }} />
          : selected !== null ? <ComponentPage key={selected} id={selected} />
          : <section className="panel empty welcome"><div className="circuit-symbol" aria-hidden="true">▦</div><h2>A home for your component knowledge</h2>
            <p>Select a component to view its details and datasheet revisions, or register your first component.</p>
            <button onClick={() => setRegistering(true)}>Register component</button></section>}</div>
      </div>
    </main>
    <footer>Engineering Knowledge Hub <span>Foundation · Datasheet management</span></footer>
  </div>;
}
