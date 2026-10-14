import { useSyncExternalStore } from "react";
import { jarvis, type Snapshot } from "../state/controller.ts";

/** The app state; components re-render only when the snapshot (or the selected part) changes. */
export function useJarvis<T = Snapshot>(select?: (s: Snapshot) => T): T {
  const snap = useSyncExternalStore(jarvis.subscribe, jarvis.getSnapshot, jarvis.getSnapshot);
  return select ? select(snap) : (snap as T);
}
