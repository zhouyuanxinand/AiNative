/**
 * 全局状态 Provider——等价于原 SPA 的顶层全局变量。
 *
 * 所有原 SPA 通过 `let xxx` 声明、通过 `getElementById` 读写的状态，
 * 都收敛到这里，由 React Context 统一管理。
 */
import {
  createContext,
  useContext,
  useState,
  useCallback,
  useRef,
  type ReactNode,
} from 'react';
import type {
  ProductType,
  ModelItem,
  HistoryItem,
  PrecheckResponse,
  TemplateEditPlan,
  JobResult,
  JobStatus,
  HealthResponse,
} from '../types';
import { UI_MODE_KEY, type UIMode, type WorkspaceView, type ReviewTab, type ManagementKind } from '../constants';

// ── 表单字段 ──────────────────────────────────────────
export interface TaskbookForm {
  productType: string;
  productDomain: string;
  developmentProcess: string;
  coverPhase: string;
  productSeries: string;
  organizationScope: string;
  templateInstruction: string;
  templateEditConfirmed: boolean;
  failOnRegression: boolean;
}

const INITIAL_FORM: TaskbookForm = {
  productType: '',
  productDomain: '',
  developmentProcess: '全新',
  coverPhase: '',
  productSeries: '',
  organizationScope: 'non_central_research',
  templateInstruction: '',
  templateEditConfirmed: false,
  failOnRegression: false,
};

// ── 日志条目 ──────────────────────────────────────────
export interface LogEntry {
  text: string;
  cls: string;
}

// ── Context 值 ────────────────────────────────────────
interface TaskbookContextValue {
  // 表单
  form: TaskbookForm;
  setFormField: <K extends keyof TaskbookForm>(key: K, value: TaskbookForm[K]) => void;
  resetForm: () => void;

  // 文件
  files: { tech: File | null; spec: File | null };
  uploadedFiles: { tech: File[]; spec: File[] };
  setFiles: (files: { tech: File | null; spec: File | null }) => void;
  setUploadedFiles: (uf: { tech: File[]; spec: File[] }) => void;

  // 目录
  productCatalog: ProductType[];
  setProductCatalog: (c: ProductType[]) => void;
  modelCatalog: ModelItem[];
  setModelCatalog: (c: ModelItem[]) => void;

  // 模型
  selectedModelKey: string;
  setSelectedModelKey: (k: string) => void;
  selectedModelReady: boolean | null;
  setSelectedModelReady: (r: boolean | null) => void;

  // 后端
  backendHealthReady: boolean | null;
  setBackendHealthReady: (r: boolean | null) => void;
  backendHealth: HealthResponse | null;
  setBackendHealth: (r: HealthResponse | null) => void;
  backendReadyForGeneration: boolean | null;
  localDefaultsReady: boolean;
  setLocalDefaultsReady: (r: boolean) => void;
  localDefaultFiles: string;
  setLocalDefaultFiles: (s: string) => void;

  // 任务
  currentJid: string | null;
  setCurrentJid: (jid: string | null) => void;
  jobStatus: JobStatus | 'idle';
  setJobStatus: (status: JobStatus | 'idle') => void;
  currentStep: number;
  setCurrentStep: (n: number) => void;
  progressPercent: number;
  setProgressPercent: (n: number) => void;
  progressLiveText: string;
  setProgressLiveText: (s: string) => void;
  progressLiveClass: string;
  setProgressLiveClass: (s: string) => void;
  isRunning: boolean;
  setIsRunning: (b: boolean) => void;
  isCancelled: boolean;
  setIsCancelled: (b: boolean) => void;

  // 日志
  logs: LogEntry[];
  setLogs: (l: LogEntry[]) => void;
  addLog: (msg: string, cls?: string) => void;

  // 结果
  jobResult: JobResult | null;
  setJobResult: (r: JobResult | null) => void;
  resultBlocked: boolean;
  setResultBlocked: (b: boolean) => void;

  // 预检
  precheck: PrecheckResponse | null;
  setPrecheck: (p: PrecheckResponse | null) => void;

  // 模板编辑
  templateEditPlan: TemplateEditPlan | null;
  setTemplateEditPlan: (p: TemplateEditPlan | null) => void;
  templateEditStatus: string;
  setTemplateEditStatus: (s: string) => void;
  templatePreviewLoading: boolean;
  setTemplatePreviewLoading: (b: boolean) => void;

  // 回归基线
  baselineDocx: File | null;
  setBaselineDocx: (f: File | null) => void;
  baselineJson: File | null;
  setBaselineJson: (f: File | null) => void;

  // 历史
  history: HistoryItem[];
  setHistory: (h: HistoryItem[]) => void;

  // 验证
  validationTouched: Set<string>;
  addToValidationTouched: (id: string) => void;
  validationSubmitted: boolean;
  setValidationSubmitted: (b: boolean) => void;
  clearValidationTouched: () => void;

  // 布局
  sidebarExpanded: boolean;
  toggleSidebar: () => void;
  uiMode: UIMode;
  setUIMode: (m: UIMode) => void;
  workspaceView: WorkspaceView;
  setWorkspaceView: (v: WorkspaceView) => void;
  managementKind: ManagementKind | null;
  setManagementKind: (k: ManagementKind | null) => void;
  reviewTab: ReviewTab;
  setReviewTab: (t: ReviewTab) => void;
  showUploadCard: boolean;
  setShowUploadCard: (b: boolean) => void;
  showProgressCard: boolean;
  setShowProgressCard: (b: boolean) => void;
  showResultCard: boolean;
  setShowResultCard: (b: boolean) => void;
  resultEmpty: boolean;
  setResultEmpty: (b: boolean) => void;
  helpOpen: boolean;
  setHelpOpen: (b: boolean) => void;

  // Toast
  toastMessage: string;
  toastType: string;
  showToast: (msg: string, type?: string) => void;
}

const TaskbookContext = createContext<TaskbookContextValue | null>(null);

export function TaskbookProvider({ children }: { children: ReactNode }) {
  // 表单
  const [form, setForm] = useState<TaskbookForm>(INITIAL_FORM);
  const setFormField = useCallback(<K extends keyof TaskbookForm>(key: K, value: TaskbookForm[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  }, []);
  const resetForm = useCallback(() => setForm(INITIAL_FORM), []);

  // 文件
  const [files, setFilesState] = useState<{ tech: File | null; spec: File | null }>({
    tech: null,
    spec: null,
  });
  const [uploadedFiles, setUploadedFilesState] = useState<{ tech: File[]; spec: File[] }>({
    tech: [],
    spec: [],
  });
  const setFiles = useCallback((f: typeof files) => setFilesState(f), []);
  const setUploadedFiles = useCallback((uf: typeof uploadedFiles) => setUploadedFilesState(uf), []);

  // 目录
  const [productCatalog, setProductCatalog] = useState<ProductType[]>([]);
  const [modelCatalog, setModelCatalog] = useState<ModelItem[]>([]);

  // 模型
  const [selectedModelKey, setSelectedModelKey] = useState('');
  const [selectedModelReady, setSelectedModelReady] = useState<boolean | null>(null);

  // 后端
  const [backendHealthReady, setBackendHealthReady] = useState<boolean | null>(null);
  const [backendHealth, setBackendHealth] = useState<HealthResponse | null>(null);
  const [localDefaultsReady, setLocalDefaultsReady] = useState(false);
  const [localDefaultFiles, setLocalDefaultFiles] = useState('');

  // 任务
  const [currentJid, setCurrentJid] = useState<string | null>(null);
  const [jobStatus, setJobStatus] = useState<JobStatus | 'idle'>('idle');
  const [currentStep, setCurrentStep] = useState(1);
  const [progressPercent, setProgressPercent] = useState(0);
  const [progressLiveText, setProgressLiveText] = useState('正在连接受控工作流…');
  const [progressLiveClass, setProgressLiveClass] = useState('progress-live waiting');
  const [isRunning, setIsRunning] = useState(false);
  const [isCancelled, setIsCancelled] = useState(false);

  // 日志
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const addLog = useCallback((msg: string, cls?: string) => {
    setLogs((prev) => [...prev, { text: msg, cls: cls || '' }]);
  }, []);

  // 结果
  const [jobResult, setJobResult] = useState<JobResult | null>(null);
  const [resultBlocked, setResultBlocked] = useState(false);

  // 预检
  const [precheck, setPrecheck] = useState<PrecheckResponse | null>(null);

  // 模板编辑
  const [templateEditPlan, setTemplateEditPlan] = useState<TemplateEditPlan | null>(null);
  const [templateEditStatus, setTemplateEditStatus] = useState('');
  const [templatePreviewLoading, setTemplatePreviewLoading] = useState(false);

  // 回归基线
  const [baselineDocx, setBaselineDocx] = useState<File | null>(null);
  const [baselineJson, setBaselineJson] = useState<File | null>(null);

  // 历史
  const [history, setHistory] = useState<HistoryItem[]>([]);

  // 验证
  const validationTouched = useRef(new Set<string>()).current;
  const [validationSubmitted, setValidationSubmitted] = useState(false);
  const addToValidationTouched = useCallback((id: string) => {
    validationTouched.add(id);
  }, [validationTouched]);
  const clearValidationTouched = useCallback(() => validationTouched.clear(), [validationTouched]);

  // 布局
  const [sidebarExpanded, setSidebarExpanded] = useState(true);
  const toggleSidebar = useCallback(() => setSidebarExpanded((p) => !p), []);
  const [uiMode, setUIModeState] = useState<UIMode>(() => {
    try {
      return localStorage.getItem(UI_MODE_KEY) === 'expert' ? 'expert' : 'compact';
    } catch {
      return 'compact';
    }
  });
  const setUIMode = useCallback((mode: UIMode) => {
    const normalized: UIMode = mode === 'expert' ? 'expert' : 'compact';
    setUIModeState(normalized);
    try {
      localStorage.setItem(UI_MODE_KEY, normalized);
    } catch {
      /* ignore */
    }
  }, []);
  const [workspaceView, setWorkspaceView] = useState<WorkspaceView>('generate');
  const [managementKind, setManagementKind] = useState<ManagementKind | null>(null);
  const [reviewTab, setReviewTab] = useState<ReviewTab>('result');
  const [showUploadCard, setShowUploadCard] = useState(true);
  const [showProgressCard, setShowProgressCard] = useState(false);
  const [showResultCard, setShowResultCard] = useState(false);
  const [resultEmpty, setResultEmpty] = useState(true);
  const [helpOpen, setHelpOpen] = useState(false);

  // Toast
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [toastMessage, setToastMessage] = useState('');
  const [toastType, setToastType] = useState('');
  const showToast = useCallback((msg: string, type = '') => {
    setToastMessage(msg);
    setToastType(type);
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => {
      setToastMessage('');
      setToastType('');
    }, 2200);
  }, []);

  // backendReadyForGeneration 始终由最新状态派生，避免 setState 后读取旧闭包。
  const backendReadyForGeneration =
    backendHealthReady === false || selectedModelReady === false
      ? false
      : backendHealthReady === true && selectedModelReady === true
        ? true
        : null;

  const value: TaskbookContextValue = {
    form,
    setFormField,
    resetForm,
    files,
    uploadedFiles,
    setFiles,
    setUploadedFiles,
    productCatalog,
    setProductCatalog,
    modelCatalog,
    setModelCatalog,
    selectedModelKey,
    setSelectedModelKey,
    selectedModelReady,
    setSelectedModelReady,
    backendHealthReady,
    setBackendHealthReady,
    backendHealth,
    setBackendHealth,
    backendReadyForGeneration,
    localDefaultsReady,
    setLocalDefaultsReady,
    localDefaultFiles,
    setLocalDefaultFiles,
    currentJid,
    setCurrentJid,
    jobStatus,
    setJobStatus,
    currentStep,
    setCurrentStep,
    progressPercent,
    setProgressPercent,
    progressLiveText,
    setProgressLiveText,
    progressLiveClass,
    setProgressLiveClass,
    isRunning,
    setIsRunning,
    isCancelled,
    setIsCancelled,
    logs,
    setLogs,
    addLog,
    jobResult,
    setJobResult,
    resultBlocked,
    setResultBlocked,
    precheck,
    setPrecheck,
    templateEditPlan,
    setTemplateEditPlan,
    templateEditStatus,
    setTemplateEditStatus,
    templatePreviewLoading,
    setTemplatePreviewLoading,
    baselineDocx,
    setBaselineDocx,
    baselineJson,
    setBaselineJson,
    history,
    setHistory,
    validationTouched,
    addToValidationTouched,
    validationSubmitted,
    setValidationSubmitted,
    clearValidationTouched,
    sidebarExpanded,
    toggleSidebar,
    uiMode,
    setUIMode,
    workspaceView,
    setWorkspaceView,
    managementKind,
    setManagementKind,
    reviewTab,
    setReviewTab,
    showUploadCard,
    setShowUploadCard,
    showProgressCard,
    setShowProgressCard,
    showResultCard,
    setShowResultCard,
    resultEmpty,
    setResultEmpty,
    helpOpen,
    setHelpOpen,
    toastMessage,
    toastType,
    showToast,
  };

  return <TaskbookContext.Provider value={value}>{children}</TaskbookContext.Provider>;
}

export function useTaskbook(): TaskbookContextValue {
  const ctx = useContext(TaskbookContext);
  if (!ctx) throw new Error('useTaskbook must be used within TaskbookProvider');
  return ctx;
}
