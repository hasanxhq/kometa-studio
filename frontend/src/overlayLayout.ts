// Where an overlay lands on a poster, on Kometa's 1000×1500 canvas. Kometa draws the real thing; this is for placing it. A default's
// starting values and rules come from its own file, and its template variables go on top.

import type { OverlayLayout, PlexItem } from "./api";

export const POSTER_WIDTH = 1000;
export const POSTER_HEIGHT = 1500;

type Vars = Record<string, unknown>;

export type Box = { key: string; label: string; x: number; y: number; width: number; height: number; color: string; radius: number; textColor?: string };

/** One of Kometa's template conditions: every key must match. A list means any of these, `.exists` and `.not` as in Kometa. */
function matches(condition: Record<string, unknown>, vars: Vars): boolean {
  return Object.entries(condition).every(([key, wanted]) => {
    if (key === "value") return true;
    const name = key.replace(/\.(exists|not)$/, "");
    const actual = vars[name];
    if (key.endsWith(".exists")) return (actual !== undefined) === wanted;
    const hit = Array.isArray(wanted) ? wanted.includes(actual) : actual === wanted;
    return key.endsWith(".not") ? !hit : hit;
  });
}

const usable = (value: unknown): value is string | number => typeof value === "number" || (typeof value === "string" && !value.includes("<<"));

/** The layout's values with these template variables, which win over the default's own rules. */
export function resolveLayout(layout: OverlayLayout | undefined, own: Vars): Vars {
  const vars: Vars = { ...layout?.variables, ...own };
  // The alignments first: the offsets' rules look at them.
  const rules = Object.entries(layout?.conditionals ?? {}).sort(([a], [b]) => Number(b.endsWith("_align")) - Number(a.endsWith("_align")));
  for (const [key, rule] of rules) {
    if (own[key] !== undefined) continue;
    const hit = rule.conditions.find((condition) => matches(condition, vars));
    const value = usable(hit?.value) ? hit.value : rule.default; // a value that's another variable can't be placed by
    if (usable(value)) vars[key] = value;
  }
  return vars;
}

const pixels = (value: unknown, size: number) => (typeof value === "string" && value.endsWith("%") ? (Number(value.slice(0, -1)) / 100) * size : Number(value ?? 0) || 0);

/** A box from its alignment and offsets, as Kometa measures them: in from the aligned edge, or out from the centre. */
export function place(vars: Vars, width: number, height: number): { x: number; y: number } {
  const h = String(vars.horizontal_align ?? "left");
  const v = String(vars.vertical_align ?? "top");
  const across = pixels(vars.horizontal_offset, POSTER_WIDTH);
  const down = pixels(vars.vertical_offset, POSTER_HEIGHT);
  return {
    x: h === "left" ? across : h === "right" ? POSTER_WIDTH - width - across : (POSTER_WIDTH - width) / 2 + across,
    y: v === "top" ? down : v === "bottom" ? POSTER_HEIGHT - height - down : (POSTER_HEIGHT - height) / 2 + down,
  };
}

// horizontal_position has left2, center_left and so on; the grid only needs which side.
const side = (value: unknown) => String(value ?? "").split(/[_0-9]/)[0];

const RATING_LABELS: Record<string, string> = { critic: "Critic", audience: "Audience", user: "User" };

/** The boxes one layer draws. Ratings draws up to three, side by side or stacked. */
export function layerBoxes(key: string, label: string, layout: OverlayLayout | undefined, own: Vars): Box[] {
  const vars = resolveLayout(layout, own);
  const width = Number(vars.back_width) || 305;
  const height = Number(vars.back_height) || 105;
  const style = { color: typeof vars.back_color === "string" ? vars.back_color : "#00000099", radius: Number(vars.back_radius) || 30 };
  if (layout?.moved_by !== "position") return [{ key, label, ...place(vars, width, height), width, height, ...style }];
  const ratings = [1, 2, 3].map((n) => vars[`rating${n}`]).filter((rating): rating is string => typeof rating === "string" && rating !== "none");
  const names = ratings.length ? ratings.map((rating) => RATING_LABELS[rating] ?? rating.toUpperCase()) : [label];
  const across = vars.rating_alignment === "horizontal";
  const gap = across ? 15 : 100;
  const group = { width: across ? names.length * (width + gap) - gap : width, height: across ? height : names.length * (height + gap) - gap };
  const margin = 30;
  const { x, y } = place(
    { horizontal_align: side(vars.horizontal_position) || "left", vertical_align: side(vars.vertical_position) || "top", horizontal_offset: side(vars.horizontal_position) === "center" ? 0 : margin, vertical_offset: side(vars.vertical_position) === "center" ? 0 : margin },
    group.width,
    group.height,
  );
  return names.map((name, index) => ({
    key: `${key}-${index}`,
    label: name,
    x: across ? x + index * (width + gap) : x,
    y: across ? y : y + index * (height + gap),
    width,
    height,
    ...style,
  }));
}

/** "top-left", as the layer list says it. */
export function whereItIs(layout: OverlayLayout | undefined, own: Vars): string {
  const vars = resolveLayout(layout, own);
  const position = layout?.moved_by === "position";
  const h = position ? side(vars.horizontal_position) || "left" : String(vars.horizontal_align ?? "left");
  const v = position ? side(vars.vertical_position) || "top" : String(vars.vertical_align ?? "top");
  return h === v ? h : `${v}-${h}`;
}

const AUDIO: Record<string, string> = { truehd: "TRUEHD", eac3: "DD+", ac3: "DD", dca: "DTS", "dca-ma": "DTS-HD", aac: "AAC", flac: "FLAC", opus: "OPUS" };

/** What a layer says on this title, where Plex's listing can tell. */
export function layerText(name: string, label: string, item: PlexItem | null): string {
  if (name === "resolution") {
    const resolution = item?.video_resolution;
    if (!resolution) return item ? label : "4K";
    return /^\d+$/.test(resolution) ? `${resolution}P` : resolution.toUpperCase();
  }
  if (name === "audio_codec" && item?.audio_codec) return AUDIO[item.audio_codec] ?? item.audio_codec.toUpperCase();
  return label;
}
