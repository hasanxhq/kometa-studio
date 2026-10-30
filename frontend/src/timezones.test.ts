import { describe, expect, it } from "vitest";

import { formatTimezoneLabel, formatUtcOffset, timezoneOptions } from "./timezones";

describe("timezone labels", () => {
  // A fixed instant: Kolkata is UTC+05:30 year-round; New York is on EDT (UTC−04:00).
  const at = new Date("2026-06-15T12:00:00Z");

  it("formats UTC offset and the IANA name", () => {
    expect(formatUtcOffset("Asia/Kolkata", at)).toBe("+05:30");
    expect(formatTimezoneLabel("Asia/Kolkata", at)).toBe("UTC +05:30 (Asia/Kolkata)");
    expect(formatTimezoneLabel("America/New_York", at)).toBe("UTC -04:00 (America/New_York)");
    expect(formatTimezoneLabel("UTC", at)).toBe("UTC +00:00 (UTC)");
  });

  it("lists zones sorted by offset, including UTC", () => {
    const options = timezoneOptions(at, ["Asia/Kolkata"]);
    expect(options.find((option) => option.value === "Asia/Kolkata")?.label).toBe("UTC +05:30 (Asia/Kolkata)");
    expect(options.find((option) => option.value === "UTC")?.label).toBe("UTC +00:00 (UTC)");
    const offsets = options.map((option) => option.offsetMinutes);
    expect(offsets).toEqual([...offsets].sort((a, b) => a - b));
  });
});
