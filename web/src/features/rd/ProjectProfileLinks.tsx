import { useState } from 'react';
import { Button, Modal } from 'antd';
import { ProjectProfileDetail, type ProfileKind } from './ProjectProfiles';
import type { Project, ResearchCase } from './types';
import './projectProfileLinks.css';

/** Inspect related project facts without leaving the requirement or its unsaved draft. */
export function ProjectProfileLinks({ project, researchCase, kind }: {
  project: Project; researchCase?: ResearchCase; kind?: ProfileKind;
}) {
  const [opened, setOpened] = useState<ProfileKind | null>(null);
  const kinds: ProfileKind[] = kind ? [kind] : ['customer', 'product'];
  return <>
    <div className="rd-profile-links" aria-label="相关画像">
      {kinds.map(item => <Button key={item} type="link" size="small" onClick={() => setOpened(item)}>{item === 'customer' ? '客户画像' : '产品画像'}</Button>)}
    </div>
    <Modal open={opened !== null} title={opened === 'customer' ? '客户画像' : '产品画像'}
      onCancel={() => setOpened(null)} width={1040} className="rd-profile-inspector" destroyOnHidden
      footer={<Button onClick={() => setOpened(null)}>返回办理</Button>}>
      {opened && <ProjectProfileDetail kind={opened} project={project} researchCase={researchCase} />}
    </Modal>
  </>;
}
