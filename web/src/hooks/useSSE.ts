/**
 * SSE + 轮询降级 hook——从原 SPA listenSSE + startProgressPolling 原样迁移。
 *
 * EventSource 连接 /api/stream/{jid} 接收实时进度；如果断线则降级为
 * /api/status/{jid} 轮询，每 3 秒一次。收到 done/blocked/error/cancelled
 * 后自动停止。
 */
import { useRef, useCallback } from 'react';
import { useTaskbook } from './useTaskbook';
import { getJobStatus } from '../api/jobs';
import { STEP_KEYWORDS } from '../constants';
import type { SSEMessage } from '../types';

interface UseSSECallbacks {
  onDone: (msg: SSEMessage) => void;
  onBlocked: (msg: SSEMessage) => void;
  onError: (msg: SSEMessage) => void;
  onCancelled: () => void;
}

export function useSSE(callbacks: UseSSECallbacks) {
  const {
    addLog,
    setCurrentStep,
    setProgressPercent,
    setProgressLiveText,
    setProgressLiveClass,
    setIsRunning,
    setIsCancelled,
    showToast,
  } = useTaskbook();

  const eventSourceRef = useRef<EventSource | null>(null);
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const lastLogCountRef = useRef(0);

  const clearAll = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }, []);

  const handleLog = useCallback(
    (msg: string, eventNumber = 0) => {
      if (!eventNumber || eventNumber > lastLogCountRef.current) addLog(msg);
      lastLogCountRef.current = Math.max(
        lastLogCountRef.current,
        eventNumber || lastLogCountRef.current + 1,
      );
      // 进度条 & 步骤
      for (const [stepStr, kws] of Object.entries(STEP_KEYWORDS)) {
        if (kws.some((kw) => msg.includes(kw))) {
          const step = parseInt(stepStr, 10);
          setCurrentStep(step);
          setProgressPercent((step / 6) * 100);
        }
      }
    },
    [addLog, setCurrentStep, setProgressPercent],
  );

  const handleMessage = useCallback(
    (d: SSEMessage) => {
      if (d.type === 'log') {
        handleLog(d.msg || '', Number((window.EventSource as unknown as { lastEventId?: string }) || 0) || 0);
        // EventSource 的 lastEventId 在 e.lastEventId 上
      }
      if (d.type === 'heartbeat') {
        lastLogCountRef.current = Math.max(lastLogCountRef.current, Number(d.log_count || 0));
        const elapsed = Number(d.elapsed || 0);
        const seconds = Math.floor(elapsed);
        const mins = Math.floor(seconds / 60);
        const rest = String(seconds % 60).padStart(2, '0');
        setProgressLiveClass('progress-live waiting');
        const noNewLogHint =
          elapsed >= 15 && d.status !== 'cancelling'
            ? ' · 模型调用期间日志可能暂不新增，不是页面卡死'
            : '';
        setProgressLiveText(
          `${d.stage || '正在处理'} · 已耗时 ${mins}:${rest} · 已收到 ${lastLogCountRef.current} 条进度${noNewLogHint}`,
        );
      }
      if (d.type === 'done') {
        clearAll();
        setProgressLiveClass('progress-live ok');
        setProgressLiveText('受控工作流已完成，正在加载交付结果…');
        setIsRunning(false);
        callbacks.onDone(d);
      }
      if (d.type === 'blocked') {
        clearAll();
        setProgressLiveClass('progress-live err');
        setProgressLiveText('文件已生成，但未通过交付门禁；可下载复核件');
        setIsRunning(false);
        callbacks.onBlocked(d);
      }
      if (d.type === 'error') {
        clearAll();
        setProgressLiveClass('progress-live err');
        setProgressLiveText('受控工作流失败');
        setIsRunning(false);
        addLog('❌ ' + (d.msg || ''), 'err');
        callbacks.onError(d);
      }
      if (d.type === 'cancelled') {
        clearAll();
        setIsRunning(false);
        callbacks.onCancelled();
      }
    },
    [
      addLog,
      callbacks,
      clearAll,
      handleLog,
      setIsRunning,
      setProgressLiveClass,
      setProgressLiveText,
    ],
  );

  const startProgressPolling = useCallback(
    (jid: string) => {
      if (pollTimerRef.current) return;
      pollTimerRef.current = setInterval(async () => {
        try {
          const data = await getJobStatus(jid, lastLogCountRef.current);
          const base = Number(data.log_offset || 0);
          const skip = Math.max(0, lastLogCountRef.current - base);
          (data.log || []).slice(skip).forEach((msg) => addLog(msg));
          lastLogCountRef.current = Math.max(
            lastLogCountRef.current,
            Number(data.log_count || 0),
          );
          if (data.status === 'done') {
            clearAll();
            callbacks.onDone({ type: 'done', jid, result: data.result });
          } else if (data.status === 'blocked') {
            clearAll();
            callbacks.onBlocked({ type: 'blocked', jid, result: data.result });
          } else if (data.status === 'error') {
            clearAll();
            addLog('❌ ' + (data.error || '任务失败'), 'err');
            setIsRunning(false);
            callbacks.onError({ type: 'error', msg: data.error });
          } else if (data.status === 'cancelled') {
            clearAll();
            setIsRunning(false);
            callbacks.onCancelled();
          }
        } catch {
          /* SSE 仍会负责重连；轮询不再打断用户界面 */
        }
      }, 3000);
    },
    [addLog, callbacks, clearAll, setIsRunning],
  );

  const listenSSE = useCallback(
    (jid: string, eventSource: EventSource) => {
      eventSourceRef.current = eventSource;
      eventSource.onmessage = (e: MessageEvent) => {
        let d: SSEMessage;
        try {
          d = JSON.parse(e.data) as SSEMessage;
        } catch {
          addLog('⚠ 收到了无法解析的进度消息', 'warn');
          return;
        }
        if (d.type === 'log') {
          const eventNumber = Number(e.lastEventId || 0);
          if (!eventNumber || eventNumber > lastLogCountRef.current) addLog(d.msg || '');
          lastLogCountRef.current = Math.max(
            lastLogCountRef.current,
            eventNumber || lastLogCountRef.current + 1,
          );
          // 步骤检测
          for (const [stepStr, kws] of Object.entries(STEP_KEYWORDS)) {
            if (kws.some((kw) => (d.msg || '').includes(kw))) {
              const step = parseInt(stepStr, 10);
              setCurrentStep(step);
              setProgressPercent((step / 6) * 100);
            }
          }
          return;
        }
        handleMessage(d);
      };
      eventSource.onerror = () => {
        addLog('⚠ 进度连接暂时中断，改用状态轮询并等待自动重连', 'warn');
        startProgressPolling(jid);
      };
      startProgressPolling(jid);
    },
    [addLog, callbacks, handleMessage, setCurrentStep, setProgressPercent, startProgressPolling],
  );

  const resetSSE = useCallback(() => {
    clearAll();
    lastLogCountRef.current = 0;
  }, [clearAll]);

  return { listenSSE, resetSSE, clearAll };
}
