import { useState } from 'react';
import { rdCatalogResource } from './api';
import { TeamConfiguration } from './TeamConfiguration';
import { messageOf } from './presentation';
export function TeamResourceDetail({ id, version }: { id:string;version:string|number }) {
  const [configuration,setConfiguration]=useState<Record<string,unknown>|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  return <details className="rd-disclosure" onToggle={event=>{if(!event.currentTarget.open || configuration || busy)return;setBusy(true);void rdCatalogResource(id,version).then(item=>{setConfiguration((item as typeof item & {configuration?:Record<string,unknown>}).configuration ?? {});setError('');}).catch(reason=>{setConfiguration(null);setError(messageOf(reason));}).finally(()=>setBusy(false));}}><summary>查看固定专家团组成 · {id} V{version}</summary>{busy && <p role="status">正在核对当前获准固定版…</p>}{error && <p className="rd-error" role="alert">{error}</p>}{configuration && <TeamConfiguration configuration={configuration} />}</details>;
}
