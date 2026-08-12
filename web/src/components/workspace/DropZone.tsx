/** 拖拽上传区——tech/spec 两列。 */
import { useEffect, useRef, useState, type DragEvent } from 'react';
import { useTaskbook } from '../../hooks/useTaskbook';
import { selectedFileIdentity, describeSelectedFile, formatFileSize } from '../../lib/dom';

type FileKey = 'tech' | 'spec';

const LABELS: Record<FileKey, { title: string; subtitle: string; hint: string }> = {
  tech: {
    title: '需求文件',
    subtitle: '技术要求 / 技术协议 / 沟通指导书 / 技术规格书',
    hint: '支持一次选择或拖入多个 DOCX，首份文件用于建立语义主线',
  },
  spec: {
    title: '产品规范',
    subtitle: '',
    hint: '可一次选择或拖入多个 DOCX，用于指标与引用标准补缺',
  },
};

export function DropZone({ fileKey }: { fileKey: FileKey }) {
  const { uploadedFiles, setUploadedFiles, files, setFiles, addToValidationTouched, showToast } = useTaskbook();
  const inputRef = useRef<HTMLInputElement>(null);
  const zoneRef = useRef<HTMLDivElement>(null);
  const noticeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [notice, setNotice] = useState('');

  const config = LABELS[fileKey];

  useEffect(
    () => () => {
      if (noticeTimer.current) clearTimeout(noticeTimer.current);
    },
    [],
  );

  const showUploadNotice = (count: number) => {
    if (noticeTimer.current) clearTimeout(noticeTimer.current);
    setNotice(count > 1 ? `已添加 ${count} 个文件` : '上传完成');
    noticeTimer.current = setTimeout(() => setNotice(''), 2600);
  };

  const applyFiles = (fileList: FileList | null) => {
    const incoming = Array.from(fileList || []);
    if (!incoming.length) return;
    const valid = incoming.filter((f) => f.name.toLowerCase().endsWith('.docx'));
    if (valid.length !== incoming.length) showToast('仅支持 DOCX，其他文件已忽略', 'warn');
    const identities = new Set(uploadedFiles[fileKey].map((f) => selectedFileIdentity(f)));
    const added = valid.filter((f) => !identities.has(selectedFileIdentity(f)));
    if (!added.length) {
      if (valid.length) showToast('所选文件已在列表中', 'warn');
      return;
    }
    const newList = [...uploadedFiles[fileKey], ...added];
    const newUploaded = { ...uploadedFiles, [fileKey]: newList };
    setUploadedFiles(newUploaded);
    const newFiles = { ...files, [fileKey]: newList[0] || null };
    setFiles(newFiles);
    addToValidationTouched('files');
    showUploadNotice(added.length);
  };

  const onFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    applyFiles(e.target.files);
    if (e.target) e.target.value = '';
  };

  const onDragOver = (e: DragEvent) => {
    e.preventDefault();
    zoneRef.current?.classList.add('over');
  };

  const onDragLeave = () => {
    zoneRef.current?.classList.remove('over');
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    zoneRef.current?.classList.remove('over');
    applyFiles(e.dataTransfer.files);
  };

  const removeFile = (index: number, e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    const list = uploadedFiles[fileKey];
    if (!list[index]) return;
    const removed = list[index];
    const newList = list.filter((_, i) => i !== index);
    setUploadedFiles({ ...uploadedFiles, [fileKey]: newList });
    setFiles({ ...files, [fileKey]: newList[0] || null });
    if (inputRef.current) inputRef.current.value = '';
    if (noticeTimer.current) clearTimeout(noticeTimer.current);
    setNotice('');
    showToast(`已移除 ${removed.name}`, 'ok');
  };

  return (
    <div className="upload-column">
      <div
        ref={zoneRef}
        className={`drop-zone ${uploadedFiles[fileKey].length > 0 ? 'has-file' : ''}`}
        id={`dz-${fileKey}`}
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
      >
        <div className="icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 16V4m0 0L7 9m5-5 5 5" />
            <path d="M5 14v4a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-4" />
          </svg>
        </div>
        <div className="label">
          {config.title}
          <br />
          {config.subtitle}
        </div>
        <div className="hint">{config.hint}</div>
        <div
          className={`upload-complete-notice ${notice ? 'visible' : ''}`}
          id={`upload-notice-${fileKey}`}
          role="status"
          aria-live="polite"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
            <path d="m5 12 4 4L19 6" />
          </svg>
          <span>{notice || '上传完成'}</span>
        </div>
        <input type="file" accept=".docx" id={`f-${fileKey}`} multiple ref={inputRef} onChange={onFileInput} />
      </div>
      <div className="upload-file-list" id={`file-list-${fileKey}`} hidden={uploadedFiles[fileKey].length === 0} aria-live="polite">
        {uploadedFiles[fileKey].map((file, index) => (
          <div key={`${file.name}-${index}`} className="upload-file-row">
            <span className="file-document-icon" aria-hidden="true">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <path d="M14 2v6h6M8 13h8M8 17h6" />
              </svg>
            </span>
            <div className="filled-info">
              <b className="fname" title={file.name}>{file.name}</b>
              <span>{describeSelectedFile(file)}</span>
            </div>
            <button className="file-remove" type="button" title="移除文件" aria-label={`移除 ${file.name}`} onClick={(e) => removeFile(index, e)}>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
                <path d="M6 6l12 12M18 6 6 18" />
              </svg>
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

// 保持 formatFileSize 导出可用（某些场景需要）
export { formatFileSize };
