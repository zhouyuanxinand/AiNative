import { useEffect, useState } from 'react';

/** A short greeting, then breathing room; background tabs never spend the cycle. */
export function useGreetingBubble(enabled: boolean): boolean {
  const [shown, setShown] = useState(false);
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    function phase(visible: boolean) {
      setShown(visible);
      timer = setTimeout(() => phase(!visible), visible ? 6000 : 24000);
    }
    function synchronize() {
      clearTimeout(timer);
      if (enabled && document.visibilityState !== 'hidden') phase(true);
      else setShown(false);
    }
    synchronize();
    document.addEventListener('visibilitychange', synchronize);
    return () => { clearTimeout(timer); document.removeEventListener('visibilitychange', synchronize); };
  }, [enabled]);
  return enabled && shown;
}
