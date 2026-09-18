import { useEffect, useState } from "react";

/*
 * Global unsaved-changes registry. Any page with a dirty form calls
 * usePageUnsavedState(isDirty). The shell reads hasUnsavedChanges() to
 * intercept navigation (sider clicks, GNB clicks) and show an inline
 * confirm instead of letting the user leave silently.
 */

const listeners = new Set<() => void>();
let count = 0;

function notify() {
  for (const l of listeners) l();
}

function beforeUnloadHandler(e: BeforeUnloadEvent) {
  e.preventDefault();
  e.returnValue = "";
}

export function usePageUnsavedState(isDirty: boolean) {
  useEffect(() => {
    if (!isDirty) return;
    count += 1;
    if (count === 1) {
      window.addEventListener("beforeunload", beforeUnloadHandler);
    }
    notify();
    return () => {
      count -= 1;
      if (count === 0) {
        window.removeEventListener("beforeunload", beforeUnloadHandler);
      }
      notify();
    };
  }, [isDirty]);
}

export function hasUnsavedChanges(): boolean {
  return count > 0;
}

export function useHasUnsavedChanges(): boolean {
  const [value, setValue] = useState<boolean>(count > 0);
  useEffect(() => {
    const listener = () => setValue(count > 0);
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  }, []);
  return value;
}
