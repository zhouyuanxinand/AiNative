import { useCallback, useLayoutEffect, useRef, type RefObject } from 'react';

/** Keep a reading position per mounted workface; changing accounts clears these positions. */
export function useCaseWorkfacePosition(actorId: string, workface: string, area: RefObject<HTMLDivElement | null>) {
  const positions = useRef(new Map<string, number>());
  const actor = useRef(actorId);
  const activeWorkface = useRef(workface);
  const restoring = useRef(false);
  const frame = useRef<number>();
  const finishedFrame = useRef<number>();
  const cancelFrames = useCallback(() => {
    if (frame.current !== undefined) cancelAnimationFrame(frame.current);
    if (finishedFrame.current !== undefined) cancelAnimationFrame(finishedFrame.current);
  }, []);
  const focusWorkarea = useCallback(() => {
    cancelFrames();
    restoring.current = true;
    frame.current = requestAnimationFrame(() => {
      const scroller = area.current?.closest<HTMLElement>('.rd-application-shell');
      const key = activeWorkface.current;
      area.current?.focus({ preventScroll: true });
      const top = positions.current.get(key);
      if (scroller && top !== undefined) scroller.scrollTo({ top, behavior: 'auto' });
      else area.current?.scrollIntoView({ block: 'start', behavior: 'auto' });
      // Ignore scroll events caused by hiding the former view or restoring this view.
      finishedFrame.current = requestAnimationFrame(() => {
        if (scroller) positions.current.set(key, scroller.scrollTop);
        restoring.current = false;
      });
    });
  }, [area, cancelFrames]);

  useLayoutEffect(() => {
    if (actor.current && actor.current !== actorId) positions.current.clear();
    actor.current = actorId;
    activeWorkface.current = workface;
    const scroller = area.current?.closest<HTMLElement>('.rd-application-shell');
    const remember = () => {
      if (scroller && !restoring.current) positions.current.set(activeWorkface.current, scroller.scrollTop);
    };
    scroller?.addEventListener('scroll', remember, { passive: true });
    focusWorkarea();
    return () => { scroller?.removeEventListener('scroll', remember); cancelFrames(); };
  }, [actorId, workface, area, focusWorkarea, cancelFrames]);
  return focusWorkarea;
}
