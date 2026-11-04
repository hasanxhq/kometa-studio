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
  libraryType,
  requestProfile,
  onDownloadMissing,
  onRequestCap,
  onRequestProfile,
}: {
  library: string;
  builder: string;
  value: string;
  downloadMissing: boolean;
  requestCap: number | null;
  libraryType: "movie" | "show";
  requestProfile: string | null;
  onDownloadMissing: (value: boolean) => void;
  onRequestCap: (value: number | null) => void;
  onRequestProfile: (value: string | null) => void;
}) {
  const [help, setHelp] = useState(false);
  const settings = useQuery({ queryKey: ["requests", "settings"], queryFn: requestsApi.settings });
  const preview = useQuery({
    queryKey: ["builder", "sources", "preview", library, builder, value],
    queryFn: () => builderApi.previewSource({ library, source: { builder, value } }),
    enabled: Boolean(builder && value) && downloadMissing,
  });
  const enabled = settings.data?.settings.enabled === true;
  const app = libraryType === "show" ? "sonarr" : "radarr";
  const appName = app === "sonarr" ? "Sonarr" : "Radarr";
  const via = settings.data?.settings.via;
  // Overseerr/Jellyseerr choose the quality themselves, so a profile only means something when Studio asks Radarr/Sonarr.
  const viaSeerr = via === "seerr" || (via === "auto" && settings.data?.connected.seerr === true);
  const options = useQuery({
    queryKey: ["requests", "options"],
    queryFn: requestsApi.options,
    enabled: downloadMissing && enabled && !viaSeerr,
  });
  const profiles = options.data?.[app]?.quality_profiles ?? [];
  const defaultProfile = settings.data?.settings[app].quality_profile ?? `${appName}'s first`;
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
      {downloadMissing && enabled && !viaSeerr && (
        <Field label="Quality profile" hint="The default is set in Settings → Requests.">
          <select
            className={`${inputClass} w-56`}
            value={requestProfile ?? ""}
            onChange={(event) => onRequestProfile(event.target.value || null)}
            aria-label="Quality profile"
          >
            <option value="">{`Default (${defaultProfile})`}</option>
            {profiles.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
            {requestProfile && options.isSuccess && !profiles.includes(requestProfile) && (
              <option value={requestProfile}>{`${requestProfile} (not in ${appName}, uses the default)`}</option>
            )}
            {requestProfile && !options.isSuccess && <option value={requestProfile}>{requestProfile}</option>}
          </select>
        </Field>
      )}
      {downloadMissing && enabled && viaSeerr && (
        <p className="text-sm text-muted">Requests go through Overseerr/Jellyseerr, which picks the quality.</p>
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
