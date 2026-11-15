import { useEffect, useRef, useState } from "react";
import { ApiError } from "./api";

export type Check<T> =
  | { state: "idle" }
  | { state: "checking" }
  | { state: "ok"; value: T }
  | { state: "error"; error: ApiError };

/**
 * Ask the server about `input` once it has stopped changing for `delayMs`.
 * Only the latest answer is kept, however the requests return.
 */
export function useServerCheck<I, T>(input: I | null, ask: (i: I) => Promise<T>, delayMs = 400): Check<T> {
  const [check, setCheck] = useState<Check<T>>({ state: "idle" });
  const key = input === null ? null : JSON.stringify(input);
  const latest = useRef(0);
  const askRef = useRef(ask);
  askRef.current = ask;
  useEffect(() => {
    if (key === null) {
      setCheck({ state: "idle" });
      return;
    }
    const n = ++latest.current;
    setCheck({ state: "checking" });
    const timer = setTimeout(() => {
      askRef
        .current(JSON.parse(key) as I)
        .then((value) => n === latest.current && setCheck({ state: "ok", value }))
        .catch((e: unknown) => {
          if (n !== latest.current) return;
          setCheck({ state: "error", error: e instanceof ApiError ? e : new ApiError(String(e), 0) });
        });
    }, delayMs);
    return () => clearTimeout(timer);
  }, [key, delayMs]);
  return check;
}
