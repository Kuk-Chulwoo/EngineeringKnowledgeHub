import { useEffect, useState } from 'react';
import { api } from './api';

type Golden = { id: number; status: string; manifest_sha256: string; manifest: unknown };
type Metric = { match: number; mismatch: number; missing: number; extra: number; expected: number; covered: number; coverage: number | null };
type Row = { category: string; entity: unknown; field: string; status: string; golden: unknown; candidate: unknown };
type Evaluation = { metrics: Record<string, Metric>; rows: Row[]; wrong_value_count: number;
  missing_value_count: number; invented_value_count: number; unit: string };

export default function GoldenEvaluation({ revisionId, runId, csrf }: { revisionId: string; runId: number; csrf?: string }) {
  const [goldens, setGoldens] = useState<Golden[]>([]);
  const [selected, setSelected] = useState('');
  const [manifest, setManifest] = useState('');
  const [attest, setAttest] = useState(false);
  const [reviewed, setReviewed] = useState(false);
  const [evaluation, setEvaluation] = useState<Evaluation | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const golden = goldens.find(g => String(g.id) === selected);
  useEffect(() => {
    const controller = new AbortController();
    setSelected(''); setGoldens([]); setEvaluation(null); setReviewed(false);
    api<Golden[]>(`/revisions/${revisionId}/golden-references`, { signal: controller.signal })
      .then(value => setGoldens(Array.isArray(value) ? value : [])).catch(() => {});
    return () => controller.abort();
  }, [revisionId, runId]);
  async function action(kind: 'import' | 'approve' | 'evaluate') {
    setBusy(true); setError(''); setEvaluation(null);
    try {
      if (kind === 'evaluate') {
        setEvaluation(await api<Evaluation>(`/golden-references/${selected}/evaluations/${runId}`));
      } else {
        const payload = kind === 'import' ? { manifest: JSON.parse(manifest), manually_curated_from_source: true }
          : { expected_sha256: golden?.manifest_sha256, reviewed_against_original_pdf: true };
        const result = await api<Golden>(kind === 'import' ? '/golden-references' : `/golden-references/${selected}/approval`, {
          method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf || '' }, body: JSON.stringify(payload),
        });
        setGoldens(await api<Golden[]>(`/revisions/${revisionId}/golden-references`));
        setSelected(String(result.id)); setReviewed(false);
      }
    } catch (error) { setError(error instanceof Error ? error.message : 'Evaluation failed'); }
    finally { setBusy(false); }
  }
  return <section aria-label="Golden reference evaluation">
    <h4>Golden Reference vs AI Extraction</h4>
    <p>Comparison measures original AI candidates. Engineer corrections and approvals do not change the measured result.</p>
    <details><summary>Import manually curated golden reference</summary>
      <p>Read the original PDF and write expected values independently. Do not paste AI candidates as expected values.
        {' '}<a href="/api/v1/engineering/golden-schema" target="_blank" rel="noreferrer">Golden JSON schema</a></p>
      <label>Manually curated manifest JSON<textarea rows={10} value={manifest} onChange={e => setManifest(e.target.value)} /></label>
      <label><input type="checkbox" checked={attest} onChange={e => setAttest(e.target.checked)} />I manually curated these expected values from the original PDF, independently of AI output.</label>
      <button disabled={!csrf || busy || !attest || !manifest.trim()} onClick={() => action('import')}>Import golden draft</button>
    </details>
    <label>Golden reference<select value={selected} onChange={e => { setSelected(e.target.value); setEvaluation(null); setReviewed(false); }}>
      <option value="">Select a reference</option>
      {goldens.map(g => <option key={g.id} value={g.id}>Golden {g.id} · {g.status}</option>)}
    </select></label>
    {golden && <>
      <details><summary>Review exact golden manifest · {golden.manifest_sha256}</summary><pre className="golden-json">{JSON.stringify(golden.manifest, null, 2)}</pre></details>
      {golden.status === 'ENGINEER_DRAFT' && <>
        <label><input type="checkbox" checked={reviewed} onChange={e => setReviewed(e.target.checked)} />I reviewed this exact manifest against the original PDF.</label>
        <button disabled={!csrf || busy || !reviewed} onClick={() => action('approve')}>Approve golden reference</button>
      </>}
      <button disabled={busy || golden.status !== 'ENGINEER_APPROVED'} onClick={() => action('evaluate')}>Compare original AI candidates</button>
    </>}
    {error && <p className="error" role="alert">{error}</p>}
    {evaluation && <>
      <p>{evaluation.unit}. Wrong: {evaluation.wrong_value_count} · Missing: {evaluation.missing_value_count} · Invented: {evaluation.invented_value_count}</p>
      <table><caption>Category metrics; no combined accuracy score</caption><thead><tr><th>Category</th><th>Match / expected</th><th>Coverage</th><th>Wrong</th><th>Missing</th><th>Extra</th></tr></thead>
        <tbody>{Object.entries(evaluation.metrics).map(([category, m]) => <tr key={category}>
          <th>{category}</th><td>{m.match}/{m.expected}</td><td>{m.covered}/{m.expected}</td><td>{m.mismatch}</td><td>{m.missing}</td><td>{m.extra}</td>
        </tr>)}</tbody></table>
      <div className="evaluation-scroll"><table><thead><tr><th>Category / field</th><th>Status</th><th>Golden Reference</th><th>AI Extraction</th></tr></thead>
        <tbody>{evaluation.rows.map((row, i) => <tr key={i} className={'comparison-' + row.status.toLowerCase()}>
          <th>{row.category} · {row.field}<small>{JSON.stringify(row.entity)}</small></th><td>{row.status}</td>
          <td><pre>{JSON.stringify(row.golden, null, 2)}</pre></td><td><pre>{JSON.stringify(row.candidate, null, 2)}</pre></td>
        </tr>)}</tbody></table></div>
    </>}
  </section>;
}
