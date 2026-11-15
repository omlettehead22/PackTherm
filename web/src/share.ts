// Links that carry a study: #/study/<base64url of its JSON>. With no server to
// keep results, this is how a study is shared; opening the link fills in the form.
import type { Json } from "./types";

const toB64url = (bytes: Uint8Array) =>
  btoa(String.fromCharCode(...bytes))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");

export function encodeStudy(study: Record<string, Json>): string {
  return toB64url(new TextEncoder().encode(JSON.stringify(study)));
}

export function decodeStudy(text: string): Record<string, Json> | null {
  try {
    const b64 = text.replace(/-/g, "+").replace(/_/g, "/");
    const bin = atob(b64 + "=".repeat((4 - (b64.length % 4)) % 4));
    const doc = JSON.parse(new TextDecoder().decode(Uint8Array.from(bin, (c) => c.charCodeAt(0))));
    return doc && typeof doc === "object" && !Array.isArray(doc) ? doc : null;
  } catch {
    return null;
  }
}

export const studyLink = (study: Record<string, Json>) =>
  `${window.location.origin}${window.location.pathname}#/study/${encodeStudy(study)}`;
