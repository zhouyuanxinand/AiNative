import { useRef, type ReactNode } from 'react';
import { Button, Input, type InputRef } from 'antd';
import { CloseOutlined, SearchOutlined } from '@ant-design/icons';
import './requirementReviewTools.css';

export function RequirementReviewTools({ label, searchLabel, query, onQueryChange, filters, activeFilter, onFilterChange, onNext, nextDisabled, trailingAction }: {
  label: string; searchLabel: string; query: string; onQueryChange: (query: string) => void;
  filters: { key: string; label: string; count: number }[]; activeFilter: string; onFilterChange: (key: string) => void;
  onNext?: () => void; nextDisabled?: boolean;
  trailingAction?: ReactNode;
}) {
  const input = useRef<InputRef>(null);
  return <div className="rd-requirement-review-tools" role="region" aria-label={label}>
    <Input ref={input} aria-label={searchLabel} prefix={<SearchOutlined aria-hidden />} value={query} placeholder="搜索指标、原文、建议或澄清"
      onChange={event => onQueryChange(event.target.value)} suffix={query ? <Button type="text" size="small" aria-label="清除搜索" icon={<CloseOutlined aria-hidden />}
        onClick={() => { onQueryChange(''); input.current?.focus(); }} /> : null} />
    <div className="rd-requirement-filter-buttons" role="group" aria-label="需求状态筛选">{filters.map(filter => <Button key={filter.key} size="small"
      type={activeFilter === filter.key ? 'primary' : 'default'} aria-pressed={activeFilter === filter.key} onClick={() => onFilterChange(filter.key)}>{filter.label}（{filter.count}）</Button>)}</div>
    {onNext && <Button size="small" disabled={nextDisabled} onClick={onNext}>下一项待处理</Button>}
    {trailingAction && <div className="rd-review-primary-action">{trailingAction}</div>}
  </div>;
}
