"use client";

/** A session image's bytes as an object URL the browser can draw.
 *
 *  The image endpoint needs the user's token, which an `<img src>` cannot carry, so the file is
 *  fetched once with the auth header and kept as a blob URL for the life of the page. One
 *  in-flight promise per image: a picker and a results page asking for the same poster share
 *  the download. */

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

const cache = new Map<string, Promise<string>>();

export function imageUrl(sessionId: string, imageId: string): Promise<string> {
  const key = `${sessionId}/${imageId}`;
  let p = cache.get(key);
  if (!p) {
    p = api.images.blob(sessionId, imageId).then((b) => URL.createObjectURL(b));
    p.catch(() => cache.delete(key));
    cache.set(key, p);
  }
  return p;
}

/** Forget a deleted image so a re-upload with the same id (never happens) or a stale blob is not shown. */
export function forgetImageUrl(sessionId: string, imageId: string) {
  cache.delete(`${sessionId}/${imageId}`);
}

export function useImageUrl(sessionId: string, imageId: string | undefined): string | null {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!imageId) { setUrl(null); return; }
    let live = true;
    imageUrl(sessionId, imageId).then((u) => { if (live) setUrl(u); }).catch(() => { if (live) setUrl(null); });
    return () => { live = false; };
  }, [sessionId, imageId]);
  return url;
}
