// IANA zones labelled as "UTC +05:30 (Asia/Kolkata)" for Settings → General.

export type TimezoneOption = { value: string; label: string; offsetMinutes: number };

function offsetParts(zone: string, at: Date): { sign: "+" | "-"; hours: number; minutes: number; total: number } {
  const name = new Intl.DateTimeFormat("en-US", { timeZone: zone, timeZoneName: "longOffset" })
    .formatToParts(at)
    .find((part) => part.type === "timeZoneName")?.value;
  if (!name || name === "GMT" || name === "UTC") {
    return { sign: "+", hours: 0, minutes: 0, total: 0 };
  }
  const match = name.match(/^GMT([+-])(\d+)(?::(\d+))?$/);
  if (!match) {
    return { sign: "+", hours: 0, minutes: 0, total: 0 };
  }
  const sign = match[1] as "+" | "-";
  const hours = Number(match[2]);
  const minutes = Number(match[3] ?? 0);
  const total = (hours * 60 + minutes) * (sign === "-" ? -1 : 1);
  return { sign, hours, minutes, total };
}

/** e.g. "+05:30" or "-05:00". */
export function formatUtcOffset(zone: string, at: Date = new Date()): string {
  const { sign, hours, minutes } = offsetParts(zone, at);
  return `${sign}${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`;
}

/** e.g. "UTC +05:30 (Asia/Kolkata)". */
export function formatTimezoneLabel(zone: string, at: Date = new Date()): string {
  return `UTC ${formatUtcOffset(zone, at)} (${zone})`;
}

function supportedZones(): string[] {
  try {
    return Intl.supportedValuesOf("timeZone");
  } catch {
    return [];
  }
}

/** Every IANA zone, labelled and sorted by current UTC offset then name. */
export function timezoneOptions(at?: Date, extra: string[] = []): TimezoneOption[] {
  const when = at ?? new Date();
  // Studio's default is "UTC"; some runtimes leave it out of supportedValuesOf.
  const zones = new Set(["UTC", ...supportedZones(), ...extra.filter(Boolean)]);
  return [...zones]
    .map((value) => {
      const { total } = offsetParts(value, when);
      return { value, label: formatTimezoneLabel(value, when), offsetMinutes: total };
    })
    .sort((a, b) => a.offsetMinutes - b.offsetMinutes || a.value.localeCompare(b.value));
}
