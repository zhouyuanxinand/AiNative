import { useLayoutEffect, useRef, type CSSProperties } from 'react';
import type { ReviewBlock, ReviewDocument, ReviewParagraph } from '../../api/review';

export function allParagraphs(blocks: ReviewBlock[]): ReviewParagraph[] {
  return blocks.flatMap(block => block.kind === 'paragraph' ? [block] : block.rows.flatMap(row => row.cells.flatMap(cell => allParagraphs(cell.blocks))));
}
export function allElementIds(blocks: ReviewBlock[]): string[] {
  return blocks.flatMap(block => block.kind === 'paragraph' ? [block.id] : [block.id, ...block.rows.flatMap(row => row.cells.flatMap(cell => [cell.id, ...allElementIds(cell.blocks)]))]);
}
export function elementPath(blocks: ReviewBlock[], id: string): string[] {
  for (const block of blocks) {
    if (block.id === id) return [id];
    if (block.kind === 'table') for (const row of block.rows) for (const cell of row.cells) {
      if (cell.id === id) return [id, block.id];
      const path = elementPath(cell.blocks, id);
      if (path.length) return [...path, cell.id, block.id];
    }
  }
  return [];
}
export interface ReviewDraft { replacements: Record<string, string>; insertions: Record<string, string>; deletions: string[] }
export const emptyReviewDraft = (): ReviewDraft => ({ replacements: {}, insertions: {}, deletions: [] });
interface Props {
  document: ReviewDocument; side: 'source' | 'output'; selected?: string; highlighted: string[];
  onSelect: (id: string) => void; editing?: boolean; draft?: ReviewDraft; busy?: boolean;
  onText?: (id: string, text: string) => void; onInsert?: (id: string, text: string) => void;
  onDelete?: (id: string) => void; onCancelInsert?: (id: string) => void;
}
function GrowTextarea({ value, onChange, label, disabled }: { value: string; onChange: (text: string) => void; label: string; disabled?: boolean }) {
  const ref = useRef<HTMLTextAreaElement>(null);
  useLayoutEffect(() => { const node = ref.current; if (node) { node.style.height = 'auto'; node.style.height = `${Math.max(46, node.scrollHeight)}px`; } }, [value]);
  return <textarea ref={ref} aria-label={label} value={value} rows={2} disabled={disabled} spellCheck={false} onChange={event => onChange(event.target.value)} />;
}
export function ReviewDocumentPane(props: Props) {
  const { document, side, selected, highlighted, editing, draft, busy } = props;
  function render(block: ReviewBlock) {
    if (block.kind === 'table') return <div key={block.id} id={`review-${side}-${block.id}`} className={`review-table-scroll ${highlighted.includes(block.id) ? 'is-linked' : ''}`} data-element-id={block.id}>
      <table><tbody>{block.rows.map((row, index) => <tr key={index}>{row.cells.map(cell => <td key={cell.id} id={`review-${side}-${cell.id}`} className={highlighted.includes(cell.id) ? 'is-linked' : ''} colSpan={cell.colspan || 1} rowSpan={cell.rowspan || 1}>{cell.blocks.map(render)}</td>)}</tr>)}</tbody></table>
    </div>;
    const removed = draft?.deletions.includes(block.id);
    const changed = draft?.replacements[block.id] !== undefined;
    const text = changed ? draft!.replacements[block.id] : block.text;
    return <div key={block.id} id={`review-${side}-${block.id}`} data-element-id={block.id}
      className={`review-paragraph ${selected === block.id ? 'is-selected' : ''} ${highlighted.includes(block.id) ? 'is-linked' : ''} ${removed ? 'is-deleted' : ''} ${changed ? 'is-edited' : ''}`}
      data-heading-level={block.heading_level || undefined} style={{ '--heading-level': block.heading_level } as CSSProperties}
      onClick={() => props.onSelect(block.id)}>
      {editing && block.editable && !removed ? <GrowTextarea value={text} disabled={busy} label={`编辑正文 ${block.id}`} onChange={value => props.onText?.(block.id, value)} />
        : <div className="review-paragraph-text" role="button" tabIndex={0} aria-label={block.text ? undefined : '空白段落'}
          onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); props.onSelect(block.id); } }}>{text || '\u00a0'}</div>}
      {block.images?.map(image => <figure key={image.id}>{image.available === false || !image.src
        ? <figcaption>{image.reason || '此图片无法预览，请下载原件查看。'}</figcaption>
        : <img src={image.src} alt={image.alt || '文档中的图片'} loading="lazy" />}</figure>)}
      {editing && <div className="review-paragraph-tools">
        {!block.editable && <span>{block.edit_reason || '此段包含复杂格式，请下载 DOCX 或使用版式编辑修改。'}</span>}
        {removed ? <button type="button" disabled={busy} onClick={() => props.onDelete?.(block.id)}>撤销删除</button> : <>
          <button type="button" disabled={busy || draft?.insertions[block.id] !== undefined} onClick={() => props.onInsert?.(block.id, '')}>在下方加段落</button>
          {block.can_delete && <button type="button" disabled={busy} onClick={() => props.onDelete?.(block.id)}>删除此段</button>}
          {changed && <span>已修改，未保存</span>}
        </>}
      </div>}
      {editing && !removed && draft?.insertions[block.id] !== undefined && <div className="review-insertion">
        <span>新增段落</span><GrowTextarea value={draft.insertions[block.id]} disabled={busy} label={`新增段落 ${block.id}`} onChange={value => props.onInsert?.(block.id, value)} />
        <button type="button" disabled={busy} onClick={() => props.onCancelInsert?.(block.id)}>取消新增</button>
      </div>}
    </div>;
  }
  return <article className={`review-document review-document-${side}`} aria-label={side === 'source' ? '来源文档内容' : '任务书内容'}>{document.blocks.map(render)}</article>;
}
