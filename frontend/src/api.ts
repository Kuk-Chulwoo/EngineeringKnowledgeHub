export type Component = {
  id: number; manufacturer: string; part_number: string; description: string;
  category: string; package: string; internal_part_number: string | null;
  lifecycle_status: 'DRAFT' | 'VALIDATED' | 'ENGINEER_APPROVED' | 'RELEASED';
  created_at: string; updated_at: string;
};
export type Revision = {
  id: number; revision: string; datasheet_date: string | null; filename: string;
  uploaded_at: string; size_bytes: number; sha256: string;
};
export type Document = { id: number; title: string; revisions: Revision[] };
export type Pin = { id: number; component_id: number; pin_number: string; pin_name: string;
  source_type: 'AI_EXTRACTED' | 'USER_IMPORT' | 'MANUAL' };
export type PinTable = { source_type: Pin['source_type'] | null; count: number; pins: Pin[] };
export type PinImportIssue = { code: string; row: number | null; field: string | null; message: string };
export type PinImportPreview = { filename: string; format: 'csv' | 'xlsx' | null; valid: boolean;
  count: number; errors: PinImportIssue[]; warnings: PinImportIssue[];
  pins: Array<{ pin_number: string; pin_name: string }> };
export type Detail = Component & { documents: Document[];
  pin_summary: { count: number; source_type: Pin['source_type'] | null } };
export type SearchResult = { items: Component[]; total: number; limit: number; offset: number };
export const fileUrl = (id: number, download = false) =>
  `/api/v1/revisions/${id}/file${download ? '?download=true' : ''}`;

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch('/api/v1' + path, init);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail = body?.detail;
    throw new Error(typeof detail === 'string' ? detail :
      Array.isArray(detail) ? detail.map((item: { msg: string }) => item.msg).join('; ') :
      `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}
