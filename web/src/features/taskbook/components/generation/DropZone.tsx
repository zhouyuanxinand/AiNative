/** 拖拽上传区——tech/spec 两列。 */
import { useEffect, useRef, useState, type DragEvent } from 'react';
import { useTaskbook } from '../../hooks/useTaskbook';
import { describeSelectedFile, formatFileSize } from '../../../../shared/lib/dom';

type FileKey = 'tech' | 'spec';

const LABELS: Record<FileKey, { title: string; subtitle: string; hint: string }> = {
  tech: {
    title: '需求文件',
    subtitle: '技术要求 / 技术协议 / 沟通指导书 / 技术规格书',
    hint: '每次一份文件，支持 DOCX、DOC、PDF 或图片；转换内容须核对',
  },
  spec: {
    title: '产品规范',
    subtitle: '',
    hint: '每次一份文件，支持 DOCX、DOC、PDF 或图片；用于指标与引用标准补缺',
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
    const valid = incoming.filter((f) => /\.(docx?|pdf|png|jpe?g|bmp|tiff?|webp)$/i.test(f.name));
    if (valid.length !== incoming.length) showToast('支持 DOCX、DOC、PDF 和常见图片，其他格式未添加', 'warn');
    if (!valid.length) {
      return;
    }
    if (valid.length > 1) {
      showToast('每类输入仅接收一份文件，请单独选择；本次未添加', 'warn');
      return;
    }
    const newList = [valid[0]];
    const newUploaded = { ...uploadedFiles, [fileKey]: newList };
    setUploadedFiles(newUploaded);
    const newFiles = { ...files, [fileKey]: newList[0] || null };
    setFiles(newFiles);
    addToValidationTouched('files');
    showUploadNotice(1);
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
        <input type="file" accept=".docx,.doc,.pdf,.png,.jpg,.jpeg,.bmp,.tif,.tiff,.webp" id={`f-${fileKey}`} ref={inputRef} onChange={onFileInput} />
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
