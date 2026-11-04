// Download missing for list-source collections: only shown when the collection can have missing titles.

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";

import { requestsApi } from "../../requestsApi";
import { builderApi } from "../../builderApi";
import { Checkbox, Field, inputClass } from "../ui";

export function MissingTitles({
  library,
  builder,
  value,
  downloadMissing,
  requestCap,
  onDownloadMissing,
  onRequestCap,
}: {
  library: string;
  builder: string;
  value: string;
  downloadMissing: boolean;
  requestCap: number | null;
  onDownloadMissing: (value: boolean) => void;
  onRequestCap: (value: number | null) => void;
}) {
  const [help, setHelp] = useState(false);
  const settings = useQuery({ queryKey: ["requests", "settings"], queryFn: requestsApi.settings });
  const preview = useQuery({
    queryKey: ["builder", "sources", "preview", library, builder, value],
    queryFn: () => builderApi.previewSource({ library, source: { builder, value } }),
    enabled: Boolean(builder && value) && downloadMissing,
  });
  const enabled = settings.data?.settings.enabled === true;
  const missing = preview.data?.missing_count;
  const capText = requestCap === null ? "" : String(requestCap);

  return (
    <section className="flex flex-col gap-3" aria-labelledby="missing-titles-heading">
      <h3 id="missing-titles-heading" className="text-[15px] font-semibold">
        Missing titles
      </h3>
      <div className="flex flex-wrap items-start gap-2">
        <Checkbox checked={downloadMissing} onChange={onDownloadMissing} disabled={!enabled}>
          Download missing
          {downloadMissing && enabled && missing != null && (
            <span className="block text-xs text-muted">
              Will request {missing} missing title{missing === 1 ? "" : "s"}
            </span>
          )}
        </Checkbox>
        {!enabled && (
          <button
            type="button"
            className="mt-0.5 inline-flex size-7 shrink-0 items-center justify-center rounded-control border border-border text-xs text-muted hover:text-text"
            aria-label="Why Download missing is off"
            aria-expanded={help}
            onClick={() => setHelp((open) => !open)}
          >
            ?
          </button>
        )}
      </div>
      {help && !enabled && (
        <p className="text-sm text-muted">
          Turn on requests in{" "}
          <Link className="underline hover:text-text" to="/settings/requests">
            Settings → Requests
          </Link>{" "}
          first.
        </p>
      )}
      {downloadMissing && enabled && (
        <Field label="Most per day" hint="Empty uses the setting under Settings → Requests.">
          <input
            type="number"
            min={1}
            className={`${inputClass} w-28`}
            value={capText}
            onChange={(event) => {
              const raw = event.target.value.trim();
              if (raw === "") {
                onRequestCap(null);
                return;
              }
              const number = Number.parseInt(raw, 10);
              onRequestCap(Number.isFinite(number) ? number : null);
            }}
            aria-label="Most per day"
            placeholder="No limit"
          />
        </Field>
      )}
    </section>
  );
}
