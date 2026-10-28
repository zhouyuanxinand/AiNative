export function urlWithQuery(path: string, params: URLSearchParams): string {
  // Older intranet browsers support toString(), but not URLSearchParams.size.
  const query = params.toString();
  return query ? `${path}?${query}` : path;
}
