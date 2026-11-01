import { useRef, type MouseEvent, type PointerEvent } from 'react';

function isBackdrop(event: MouseEvent<HTMLDialogElement> | PointerEvent<HTMLDialogElement>) {
  if (event.target !== event.currentTarget) return false;
  const rect = event.currentTarget.getBoundingClientRect();
  return event.clientX < rect.left || event.clientX > rect.right
    || event.clientY < rect.top || event.clientY > rect.bottom;
}

/** Use the dialog's cancel action so draft and pending-operation guards still apply. */
export function useDialogBackdrop(onCancel: () => void) {
  const startedOutside = useRef(false);
  return {
    onPointerDown(event: PointerEvent<HTMLDialogElement>) {
      startedOutside.current = event.isPrimary && event.button === 0 && isBackdrop(event);
    },
    onPointerCancel() { startedOutside.current = false; },
    onClick(event: MouseEvent<HTMLDialogElement>) {
      const dismiss = startedOutside.current && event.button === 0 && isBackdrop(event);
      startedOutside.current = false;
      if (!dismiss) return;
      // Portalled child dialogs must not dismiss their React parent as well.
      event.stopPropagation();
      onCancel();
    },
  };
}
