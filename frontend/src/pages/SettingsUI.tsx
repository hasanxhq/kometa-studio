// Settings → UI: display options, kept in this browser.

import { useAdvanced } from "../advanced";
import { Card } from "../components/ui";

export function SettingsUI() {
  const { showAdvanced, setShowAdvanced } = useAdvanced();
  return (
    <div className="flex max-w-3xl flex-col gap-4">
      <Card title="Forms">
        <label className="flex min-h-11 items-center gap-2 text-sm">
          <input type="checkbox" className="size-4 accent-accent" checked={showAdvanced} onChange={(e) => setShowAdvanced(e.target.checked)} />
          Show Advanced
        </label>
        <p className="text-sm text-muted">
          Shows every option Kometa has in forms, run options and schedules, as the switch in the page header does. Remembered in this
          browser.
        </p>
      </Card>
    </div>
  );
}
