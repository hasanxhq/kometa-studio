// The app's navigation, arr-style (handoff v2 §8). Routes and the sidebar are both built from this list.

export type Page = {
  label: string;
  path: string;
  summary: string; // what the page will do, shown until it's built
};

export type Section = {
  label: string;
  pages: Page[];
};

export const sections: Section[] = [
  {
    label: "Libraries",
    pages: [
      {
        label: "Libraries",
        path: "/libraries",
        summary: "One card per Plex library, with its collections, overlays, defaults and operations.",
      },
      { label: "Overlays", path: "/overlays", summary: "Kometa's overlays per library: what draws them, when, and turning them off and on." },
    ],
  },
  {
    label: "Activity",
    pages: [
      { label: "Queue", path: "/activity/queue", summary: "The running and queued Kometa runs, with a live log and cancel." },
      {
        label: "History",
        path: "/activity/history",
        summary: "What each run changed, collection by collection, from Kometa's webhooks.",
      },
    ],
  },
  {
    label: "System",
    pages: [
      { label: "Status", path: "/system/status", summary: "Versions, health checks and connection problems." },
      { label: "Tasks", path: "/system/tasks", summary: "Schedules and built-in tasks, with last run, next run and Run Now." },
      { label: "Backup", path: "/system/backup", summary: "Config backups taken on every save, scheduled full backups and restore." },
      { label: "Logs", path: "/system/logs", summary: "Kometa's meta.log and the log of every run." },
      { label: "Updates", path: "/system/updates", summary: "The installed Kometa version and whether a newer one is out." },
    ],
  },
  {
    label: "Settings",
    pages: [
      { label: "General", path: "/settings/general", summary: "Port, sign-in, API key and timezone." },
      { label: "Plex", path: "/settings/plex", summary: "Sign in with Plex and pick your server." },
      { label: "Connect", path: "/settings/connect", summary: "Radarr, Sonarr, Maintainerr, TMDb and MDBList, each tested before it is saved." },
      { label: "Notifications", path: "/settings/notifications", summary: "Notifiarr, Gotify, ntfy and Apprise, and which Kometa events go where." },
      { label: "Network", path: "/settings/network", summary: "A proxy, DNS over HTTPS and IPv4 first, for Studio and Kometa, and a connection check." },
      { label: "Kometa", path: "/settings/kometa", summary: "Kometa's paths and the flags every run uses." },
      { label: "UI", path: "/settings/ui", summary: "Show Advanced by default, and other display options." },
    ],
  },
];

export const pages: Page[] = sections.flatMap((section) => section.pages);

// Pages reached from other pages rather than the sidebar; the header shows these titles.
export const otherPages: { path: string; label: string }[] = [
  { path: "/files", label: "Edit file" },
  { path: "/items", label: "Edit" },
];
