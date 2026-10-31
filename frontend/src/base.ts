// The URL base Studio is served under behind a reverse proxy (Settings → General), from the page's
// <base href>, which the server writes. "" when there's none, as in tests and `npm run dev`.

export const urlBase = new URL(document.baseURI).pathname.replace(/\/+$/, "");
