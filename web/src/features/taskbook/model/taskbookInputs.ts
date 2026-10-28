type InputValues = { source_refs: { source_id: string; version: number }[]; parameters: Record<string, unknown>; model_selection: { provider: string; name: string; id: string } };
type PackageValues = { source_refs: InputValues['source_refs']; raw_parameters: InputValues['parameters']; model_selection: InputValues['model_selection'] };

/** Object key order is a serialization detail; array order remains meaningful. */
function canonicalValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalValue);
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).sort(([left], [right]) => left < right ? -1 : left > right ? 1 : 0).map(([key, entry]) => [key, canonicalValue(entry)]));
  return value;
}
export function inputPackageMatchesForm(pack: PackageValues | undefined, form: InputValues) {
  if (!pack) return false;
  const packageValues = [pack.source_refs.map(ref => ({ source_id: ref.source_id, version: ref.version })), pack.raw_parameters, pack.model_selection];
  const formValues = [form.source_refs, form.parameters, form.model_selection];
  return JSON.stringify(canonicalValue(packageValues)) === JSON.stringify(canonicalValue(formValues));
}
