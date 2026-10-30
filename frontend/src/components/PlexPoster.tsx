// A poster from Plex, through Studio's image proxy (the Plex token stays on the server). The title stands in for
// artwork Plex doesn't have or can't send.

import { useState } from "react";

import { api } from "../api";

export function PlexPoster({ thumb, title }: { thumb: string | null; title: string }) {
  const [failed, setFailed] = useState(false);
  return (
    <div className="aspect-[2/3] overflow-hidden rounded-control border border-border bg-surface-2">
      {thumb && !failed ? (
        <img src={api.plexLibraries.imageUrl(thumb)} alt="" loading="lazy" className="size-full object-cover" onError={() => setFailed(true)} />
      ) : (
        <div className="flex size-full items-center justify-center p-2 text-center font-display text-sm text-muted">{title}</div>
      )}
    </div>
  );
}
