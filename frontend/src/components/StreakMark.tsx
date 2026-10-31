// The logo mark: a K whose upper arm is a comet, coloured by the app's tokens (brand/README.md). It sits beside the
// words "Kometa Studio", so screen readers skip it.

export function StreakMark({ size = 24 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden="true" className="shrink-0">
      <path className="fill-text" d="M14.5 10H22.5A1.5 1.5 0 0 1 24 11.5V37.5L50 54H36L24 45V52.5A1.5 1.5 0 0 1 22.5 54H14.5A1.5 1.5 0 0 1 13 52.5V11.5A1.5 1.5 0 0 1 14.5 10Z" />
      <path className="fill-accent" d="M24 35L40.35 10.55A8 8 0 1 1 50.48 22.2Z" />
    </svg>
  );
}
