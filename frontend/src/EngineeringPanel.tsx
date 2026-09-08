import { useEffect, useState, type FormEvent } from 'react';
import { api, fileUrl, type Detail } from './api';
import GoldenEvaluation from './GoldenEvaluation';

type Session = { actor: string; csrf_token: string };
type Evidence = { source_revision_id: number; page_number: number; source_text: string | null;
  printed_page_label: string | null; locator_method: string };
type Review = { sequence: number; status: string; actor_id: string; reason: string; created_at: string };
type EngineeringField = {
  id: number; key: string; value: unknown; availability: string; confidence: number | null;
  confidence_basis: string; review_status: string; latest_review_sequence: number;
  source_revision_id: number; evidence: Evidence[]; history: Review[];
  content_sha256: string; origin: string; supersedes_field_id: number | null;
};
type EngineeringEntity = { id: number; local_key: string; kind: string; fields: EngineeringField[] };
type Run = { id: number; status: string; source_revision_id: number; source_sha256: string;
  entities: EngineeringEntity[]; error_code: string | null; error_summary: string | null;
  candidate_set_sha256: string | null; created_at: string;
  provenance: { pipeline_version: string; model_identifier: string; provider?: string; prompt_version?: string; extraction_settings?: { package_scope: string }; passes?: unknown[] };
};
type Snapshot = { id: number; eligibility: string; pads_eligible: false; manifest_sha256: string };
const explain = (error: unknown) => error instanceof Error ? error.message : 'Request failed';
const terminal = (status: string) => ['SUCCEEDED', 'FAILED', 'CANCELLED'].includes(status);

function FieldReview({ field, session, onChanged }: {
  field: EngineeringField; session: Session | null; onChanged: () => Promise<void>;
}) {
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function decide(status: string) {
    if (!session) return;
    setBusy(true); setError('');
    try {
      await api(`/engineering-fields/${field.id}/reviews`, {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': session.csrf_token },
        body: JSON.stringify({ status, expected_sequence: field.latest_review_sequence, reason }),
      });
      await onChanged();
    } catch (error) { setError(explain(error)); } finally { setBusy(false); }
  }
  return <section className="engineering-field">
    <div className="section-heading"><strong>{field.key}</strong><span className="badge">{field.review_status}</span></div>
    <p className="engineering-value">{typeof field.value === 'string' ? field.value : JSON.stringify(field.value)}</p>
    <p className="muted">Availability: {field.availability} · Confidence: {field.confidence === null ? 'Not provided' : field.confidence}
      {' '}({field.confidence_basis}) · {field.origin === 'AI' ? 'AI candidate' : 'Engineer correction'}</p>
    <ul>{field.evidence.map((e, i) => <li key={i}>
      <a href={fileUrl(e.source_revision_id) + '#page=' + e.page_number} target="_blank" rel="noreferrer">
        Source revision {e.source_revision_id}, PDF page {e.page_number}</a>
      {e.printed_page_label && <span> (label {e.printed_page_label})</span>}
      <blockquote>{e.source_text || 'Region evidence; open original PDF.'}</blockquote>
    </li>)}</ul>
    <label>Review reason for {field.key}<input value={reason} onChange={e => setReason(e.target.value)} maxLength={1000} /></label>
    <div className="actions">
      <button disabled={!session || busy || !reason.trim() || field.availability !== 'PRESENT'}
        onClick={() => decide('ENGINEER_APPROVED')}>Approve field</button>
      <button className="quiet" disabled={!session || busy || !reason.trim()}
        onClick={() => decide('ENGINEER_REJECTED')}>Reject field</button>
    </div>
    {error && <p className="error" role="alert">{error}</p>}
    <details><summary>Review history ({field.history.length})</summary>
      <ol>{field.history.map(event => <li key={event.sequence}>
        {event.status} · {event.actor_id} · {new Date(event.created_at).toLocaleString()}<p>{event.reason}</p>
      </li>)}</ol>
      <small>Field {field.id} · SHA-256 {field.content_sha256}</small>
    </details>
  </section>;
}

export default function EngineeringPanel({ detail }: { detail: Detail }) {
  const revisions = detail.documents.flatMap(document => document.revisions.map(revision =>
    ({ ...revision, title: document.title })));
  const [revisionId, setRevisionId] = useState('');
  const [mode, setMode] = useState('synthetic');
  const [scope, setScope] = useState('');
  const [consent, setConsent] = useState(false);
  const [providerConfig, setProviderConfig] = useState<{ provider: string; model: string; enabled: boolean; configured: boolean } | null>(null);
  const realReady = mode === 'synthetic' || Boolean(providerConfig?.enabled && providerConfig.configured && consent && scope.trim());
  const [runs, setRuns] = useState<Run[]>([]);
  const [runId, setRunId] = useState('');
  const [run, setRun] = useState<Run | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    api<Session>('/reviewer/session', { signal: controller.signal }).then(setSession).catch(() => {});
    api<{ provider: string; model: string; enabled: boolean; configured: boolean }>('/engineering/provider-config', { signal: controller.signal })
      .then(setProviderConfig).catch(() => {});
    return () => controller.abort();
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    setRuns([]); setRunId(''); setRun(null); setSnapshot(null); setError(''); setConsent(false);
    if (revisionId) api<Run[]>(`/revisions/${revisionId}/extraction-runs`, { signal: controller.signal })
      .then(setRuns).catch(e => { if (!controller.signal.aborted) setError(explain(e)); });
    return () => controller.abort();
  }, [revisionId]);
  useEffect(() => {
    if (!runId) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const result = await api<Run>(`/extraction-runs/${runId}`, { signal: controller.signal });
        if (controller.signal.aborted) return;
        setRun(result);
        if (!terminal(result.status)) timer = setTimeout(poll, 1500);
      } catch (error) { if (!controller.signal.aborted) setError(explain(error)); }
    }
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [runId]);

  async function login(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    setBusy(true); setError('');
    try {
      setSession(await api<Session>('/reviewer/session', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(Object.fromEntries(new FormData(form))),
      }));
      form.reset();
    } catch (error) { setError(explain(error)); } finally { setBusy(false); }
  }
  async function mutate<T>(path: string, value: unknown): Promise<T> {
    return api<T>(path, { method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': session?.csrf_token || '' },
      body: JSON.stringify(value) });
  }
  async function start(retry = false) {
    setBusy(true); setError(''); setSnapshot(null);
    try {
      const result = await mutate<Run>(`/revisions/${revisionId}/extraction-runs`,
        { provider: mode, retry_of_run_id: retry ? run?.id : null, ...(mode === 'openai' ? { external_transmission_authorized: consent, settings: { package_scope: scope.trim() } } : {}) });
      setRuns(await api<Run[]>(`/revisions/${revisionId}/extraction-runs`));
      setRun(result); setRunId(String(result.id));
    } catch (error) { setError(explain(error)); } finally { setBusy(false); }
  }
  async function refresh() {
    const result = await api<Run>(`/extraction-runs/${runId}`);
    setRun(result);
    if (snapshot) setSnapshot(await api<Snapshot>(`/approved-snapshots/${snapshot.id}`));
  }
  async function cancel() {
    setBusy(true); setError('');
    try {
      await mutate(`/extraction-runs/${runId}/cancel`, {});
      await refresh();
    } catch (error) { setError(explain(error)); } finally { setBusy(false); }
  }
  async function approveSnapshot() {
    if (!run) return;
    setBusy(true); setError('');
    try {
      const ids = run.entities.flatMap(e => e.fields.filter(f => f.review_status === 'ENGINEER_APPROVED').map(f => f.id));
      const pkg = run.entities.find(e => e.kind === 'PACKAGE');
      setSnapshot(await mutate<Snapshot>('/approved-snapshots', {
        run_id: run.id, selected_package_entity_id: pkg?.id, field_ids: ids,
      }));
    } catch (error) { setError(explain(error)); } finally { setBusy(false); }
  }
  async function logout() {
    setBusy(true); setError('');
    try {
      await fetch('/api/v1/reviewer/session', { method: 'DELETE',
        headers: { 'X-CSRF-Token': session?.csrf_token || '' } }).then(response => {
          if (!response.ok) throw new Error('Sign-out failed');
        });
      setSession(null);
    } catch (error) { setError(explain(error)); } finally { setBusy(false); }
  }
  return <section aria-label="Engineering analysis">
    <h3>Engineering / AI Analysis</h3>
    <p className="engineering-notice">Synthetic extraction works offline. Real AI Extraction sends selected source text to the configured provider only after explicit authorization.
      All results require engineer review. PADS generation remains disabled.</p>
    <p><a href="/api/v1/engineering/synthetic-fixture/file">Download fabricated fixture PDF</a>.
      {' '}Upload it through Documents, then select that revision below. Other PDFs are rejected by the synthetic provider.</p>
    {session ? <p>Reviewer: <strong>{session.actor}</strong> <button className="quiet" disabled={busy} onClick={logout}>Sign out</button></p>
      : <form onSubmit={login} className="reviewer-login">
        <p className="muted">Sign in with the local engineer account. Initial setup: scripts/setup-reviewer.ps1.</p>
        <div className="fields"><label>Engineer name<input name="name" required autoComplete="username" maxLength={100} /></label>
          <label>Engineer password<input name="password" type="password" required autoComplete="current-password" maxLength={500} /></label></div>
        <button disabled={busy}>Sign in for review</button>
      </form>}
    <div className="fields">
      <label>Source document revision<select value={revisionId} disabled={busy}
        onChange={event => setRevisionId(event.target.value)}>
        <option value="">Select a revision</option>
        {revisions.map(revision => <option key={revision.id} value={revision.id}>
          {revision.title} · {revision.revision} · {revision.filename}</option>)}
      </select></label>
      <label>Extraction run<select value={runId} disabled={busy}
        onChange={event => { setRun(null); setSnapshot(null); setRunId(event.target.value); }}>
        <option value="">Select a run</option>
        {runs.map(item => <option key={item.id} value={item.id}>Run {item.id} · {item.status}</option>)}
      </select></label>
    </div>
    <label>Extraction mode<select value={mode} disabled={busy} onChange={e => { setMode(e.target.value); setConsent(false); }}>
      <option value="synthetic">Synthetic Extraction</option><option value="openai">Real AI Extraction</option>
    </select></label>
    {mode === 'openai' && <section aria-label="Real AI settings">
      <p>Provider: {providerConfig?.provider || 'Unavailable'} · Model: {providerConfig?.model || 'Not configured'} · External transmission: {providerConfig?.enabled && providerConfig.configured ? 'Enabled' : 'Disabled / not configured'}</p>
      <label>Package scope<input value={scope} maxLength={100} onChange={e => setScope(e.target.value)} placeholder="Exact package variant to extract" /></label>
      <p className="muted">Native text only. Up to 200 PDF pages scanned, 6 selected pages and 40,000 characters per pass; 16,000 output tokens per pass. Four focused passes.</p>
      <label><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)} />I authorize sending selected text from this revision to the configured OpenAI model.</label>
    </section>}
    <div className="actions"><button disabled={!session || !revisionId || busy || !realReady} onClick={() => start()}>{mode === 'synthetic' ? 'Start synthetic extraction' : 'Start Real AI Extraction'}</button>
      {run && terminal(run.status) && <button className="quiet" disabled={!session || busy || !realReady} onClick={() => start(true)}>Retry as new run</button>}
      {run && !terminal(run.status) && <button className="quiet" disabled={!session || busy} onClick={cancel}>Cancel run</button>}
    </div>
    {error && <p className="error" role="alert">{error}</p>}
    {run && <section>
      <p role="status"><strong>Run {run.id}: {run.status}</strong></p>
      {!terminal(run.status) && <p className="muted">Waiting for the local worker. Start it with scripts/start-worker.ps1.</p>}
      <small>Source revision {run.source_revision_id} · {run.provenance.pipeline_version} · {run.provenance.model_identifier}</small>
      {run.provenance.extraction_settings && <p>Package scope: {run.provenance.extraction_settings.package_scope} · Provider: {run.provenance.provider} · Prompt: {run.provenance.prompt_version}</p>}
      <details><summary>Extraction provenance and settings</summary><pre className="golden-json">{JSON.stringify(run.provenance, null, 2)}</pre></details>
      {run.error_code && <p className="error">{run.error_code}: {run.error_summary}</p>}
      {run.entities.map(entity => <details className="engineering-entity" key={entity.id}>
        <summary>{entity.local_key} · {entity.kind} · {entity.fields.length} field versions</summary>
        {entity.fields.map(field => <FieldReview key={field.id} field={field} session={session} onChanged={refresh} />)}
      </details>)}
      {run.status === 'SUCCEEDED' && <GoldenEvaluation key={run.id} revisionId={String(run.source_revision_id)} runId={run.id} csrf={session?.csrf_token} />}
      {run.status === 'SUCCEEDED' && <div className="overview-action">
        <h4>Approved snapshot</h4>
        <p className="muted">Approve every field in the single-package dataset before creating a review snapshot.
          PADS eligibility remains disabled.</p>
        <button disabled={!session || busy} onClick={approveSnapshot}>Create approved snapshot</button>
        {snapshot && <p role="status">Snapshot {snapshot.id}: {snapshot.eligibility} · PADS eligible: No</p>}
      </div>}
    </section>}
  </section>;
}
