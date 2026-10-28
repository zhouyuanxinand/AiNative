import type { ReactNode } from 'react';

export function RdSection({ title, description, children }: { title: string; description?: string; children: ReactNode }) { return <section className="rd-panel"><h2>{title}</h2>{description && <p className="rd-muted">{description}</p>}{children}</section>; }
