export type ProjectTab = 'results' | 'flow' | 'materials';
export type MaterialSection = 'requirements' | 'sources' | 'members' | 'history';
const aliases: Record<string, ProjectTab> = {
  results: 'results', overview: 'results', artifacts: 'results',
  flow: 'flow', tasks: 'flow',
  materials: 'materials', requirements: 'materials', members: 'materials', history: 'materials',
};
export function projectTabFromUrl(search: string): ProjectTab {
  return aliases[new URLSearchParams(search).get('tab') || ''] || 'results';
}
export function materialSectionFromUrl(search: string, hash = ''): MaterialSection {
  const params = new URLSearchParams(search);
  if (hash.startsWith('#requirement-')) return 'requirements';
  const value = params.get('section') || params.get('tab') || '';
  return ['sources', 'members', 'history'].includes(value) ? value as MaterialSection : 'requirements';
}
