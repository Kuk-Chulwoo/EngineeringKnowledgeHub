import { useEffect, useState, type FormEvent } from 'react';
import { api, fileUrl, type Component, type Detail, type Revision, type SearchResult } from './api';
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

function ComponentPage({ id }: { id: number }) {
  const [detail, setDetail] = useState<Detail | null>(null);
  const [tab, setTab] = useState('overview');
  const [refresh, setRefresh] = useState(0);
  const [error, setError] = useState('');
  const [viewing, setViewing] = useState<Revision | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    setError('');
    api<Detail>(`/components/${id}`, { signal: controller.signal })
      .then(setDetail).catch(error => { if (!controller.signal.aborted) setError(message(error)); });
    return () => controller.abort();
  }, [id, refresh]);
  if (!detail) return <section className="panel"><p role={error ? 'alert' : 'status'}>{error || 'Loading component…'}</p>
    {error && <button onClick={() => setRefresh(n => n + 1)}>Retry</button>}</section>;
  const count = detail.documents.reduce((total, document) => total + document.revisions.length, 0);
  return <article className="panel detail">
    <header className="component-heading"><div><p className="eyebrow">{detail.manufacturer}</p>
      <h2>{detail.part_number}</h2></div><span className="badge">{detail.category || 'Uncategorized'}</span></header>
    <p className="description">{detail.description || 'No description provided.'}</p>
    <nav className="tabs" aria-label="Component sections">
      {componentTabs.map(item => <button key={item.id} className={tab === item.id ? 'active' : ''}
        disabled={!item.enabled} title={item.enabled ? undefined : 'Planned for a future version'}
        aria-current={tab === item.id ? 'page' : undefined} onClick={() => setTab(item.id)}>{item.label}</button>)}
    </nav>
    {error && <p className="error" role="alert">{error} <button onClick={() => setRefresh(n => n + 1)}>Retry</button></p>}
    {tab === 'engineering' ? <EngineeringPanel detail={detail} /> : tab === 'overview' ? <>
      <dl className="facts">
        <div><dt>Manufacturer</dt><dd>{detail.manufacturer}</dd></div>
        <div><dt>Part Number</dt><dd>{detail.part_number}</dd></div>
        <div><dt>Category</dt><dd>{detail.category || '—'}</dd></div>
        <div><dt>Package</dt><dd>{detail.package || '—'}</dd></div>
        <div><dt>Registered</dt><dd>{time(detail.created_at)}</dd></div>
        <div><dt>Documents</dt><dd>{detail.documents.length} documents · {count} revisions</dd></div>
      </dl>
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
