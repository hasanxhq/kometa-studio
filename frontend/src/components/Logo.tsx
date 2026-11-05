// The logo (brand/README.md), coloured by the app's tokens. Paths are copied from brand/svg/mark-on-dark.svg and
// brand/build_icons.py's WORD_STAR: change them there first.

const LEFT = "M10.95 14.09L30.27 8.91A4 4 0 0 1 35.17 11.74L43.97 44.58A4 4 0 0 1 41.14 49.48L21.82 54.66A4 4 0 0 1 16.92 51.83L8.12 18.99A4 4 0 0 1 10.95 14.09Z";
const RIGHT = "M33.73 8.91L53.05 14.09A4 4 0 0 1 55.88 18.99L47.08 51.83A4 4 0 0 1 42.18 54.66L22.86 49.48A4 4 0 0 1 20.03 44.58L28.83 11.74A4 4 0 0 1 33.73 8.91Z";
const FRONT = "M22 10L42 10A4 4 0 0 1 46 14L46 48A4 4 0 0 1 42 52L22 52A4 4 0 0 1 18 48L18 14A4 4 0 0 1 22 10Z";
const STAR = "M29.5 22.5L29.5 39.5A2.5 2.5 0 0 0 34.5 39.5L34.5 22.5A2.5 2.5 0 0 0 29.5 22.5ZM38.11 24.58L23.39 33.08A2.5 2.5 0 0 0 25.89 37.42L40.61 28.92A2.5 2.5 0 0 0 38.11 24.58ZM40.61 33.08L25.89 24.58A2.5 2.5 0 0 0 23.39 28.92L38.11 37.42A2.5 2.5 0 0 0 40.61 33.08Z";
const WORD_STAR = "M26 11L26 53A6 6 0 0 0 38 53L38 11A6 6 0 0 0 26 11ZM47.19 16.3L10.81 37.3A6 6 0 0 0 16.81 47.7L53.19 26.7A6 6 0 0 0 47.19 16.3ZM53.19 37.3L16.81 16.3A6 6 0 0 0 10.81 26.7L47.19 47.7A6 6 0 0 0 53.19 37.3Z";

// The mark: three fanned posters, the front one starred. It sits beside the name, so screen readers skip it.
export function PosterMark({ size = 24 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden="true" className="shrink-0">
      <path className="fill-accent" opacity={0.3} d={LEFT} />
      <path className="fill-accent" opacity={0.55} d={RIGHT} />
      <path className="fill-accent" d={FRONT} />
      <path className="fill-on-accent" d={STAR} />
    </svg>
  );
}

// "St*arr Studio": the star is raised like an asterisk and sized in em, so it follows the text around it. Screen
// readers hear "Starr Studio".
export function Wordmark() {
  return (
    <span role="img" aria-label="Starr Studio" className="whitespace-nowrap">
      St
      <svg
        viewBox="0 0 64 64"
        aria-hidden="true"
        className="inline-block"
        style={{ width: "0.46em", height: "0.46em", verticalAlign: "0.26em", margin: "0 0.03em" }}
      >
        <path className="fill-accent" d={WORD_STAR} />
      </svg>
      arr <span className="text-accent">Studio</span>
    </span>
  );
}
