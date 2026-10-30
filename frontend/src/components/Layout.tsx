import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router";

import { useAdvanced } from "../advanced";
import { api } from "../api";
import { otherPages, pages, sections } from "../nav";

function navLinkClass({ isActive }: { isActive: boolean }) {
  return [
    "flex min-h-11 items-center rounded-control px-3 text-sm transition-colors",
    isActive ? "bg-surface-2 text-accent" : "text-muted hover:bg-surface-2 hover:text-text",
  ].join(" ");
}

function Sidebar({ onNavigate }: { onNavigate: () => void }) {
  return (
    <nav aria-label="Main" className="flex flex-col gap-5 p-3">
      {sections.map((section) =>
        section.pages.length === 1 ? (
          <NavLink key={section.label} to={section.pages[0].path} className={navLinkClass} onClick={onNavigate}>
            {section.label}
          </NavLink>
        ) : (
          <div key={section.label}>
            <h2 className="px-3 pb-1 text-xs font-medium uppercase tracking-wider text-muted">{section.label}</h2>
            <ul>
              {section.pages.map((page) => (
                <li key={page.path}>
                  <NavLink to={page.path} className={navLinkClass} onClick={onNavigate}>
                    {page.label}
                  </NavLink>
                </li>
              ))}
            </ul>
          </div>
        ),
      )}
    </nav>
  );
}

function AdvancedToggle() {
  const { showAdvanced, setShowAdvanced } = useAdvanced();
  return (
    <label className="flex min-h-11 cursor-pointer items-center gap-2 text-sm text-muted">
      <input
        type="checkbox"
        className="size-4 accent-accent"
        checked={showAdvanced}
        onChange={(event) => setShowAdvanced(event.target.checked)}
      />
      Show Advanced
    </label>
  );
}

function SignOut() {
  const queryClient = useQueryClient();
  const signOut = useMutation({ mutationFn: api.auth.logout, onSuccess: () => queryClient.resetQueries() });
  return (
    <button type="button" className="min-h-11 px-2 text-sm text-muted hover:text-text" onClick={() => signOut.mutate()}>
      Sign out
    </button>
  );
}

// Until a username and password are set, Studio answers only local addresses; say so, once, everywhere.
function SignInNotice() {
  return (
    <p role="status" className="border-b border-warn/40 bg-surface px-4 py-2 text-sm text-warn">
      Sign-in isn't set up, so anyone on your local network can use Studio.{" "}
      <Link to="/settings/general" className="underline">
        Set a username and password
      </Link>
    </p>
  );
}

export function Layout() {
  const auth = useQuery({ queryKey: ["auth"], queryFn: api.auth.status });
  const [menuOpen, setMenuOpen] = useState(false);
  const { pathname } = useLocation();
  const current = [...pages, ...otherPages].find((page) => pathname.startsWith(page.path));

  return (
    <div className="flex h-full">
      {/* Sidebar: always visible from md up, a slide-over menu below that. */}
      <aside
        className={[
          "fixed inset-y-0 left-0 z-20 w-60 overflow-y-auto border-r border-border bg-sidebar md:static md:block",
          menuOpen ? "block" : "hidden",
        ].join(" ")}
      >
        <div className="flex h-14 items-center px-6 font-display text-lg font-semibold">
          Kometa <span className="ml-1 text-accent">Studio</span>
        </div>
        <Sidebar onNavigate={() => setMenuOpen(false)} />
      </aside>
      {menuOpen && <div className="fixed inset-0 z-10 bg-black/50 md:hidden" onClick={() => setMenuOpen(false)} />}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center gap-3 border-b border-border px-4">
          <button
            type="button"
            className="flex size-11 items-center justify-center rounded-control text-muted hover:bg-surface-2 md:hidden"
            aria-label="Open menu"
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen(true)}
          >
            ☰
          </button>
          <h1 className="min-w-0 flex-1 truncate text-lg font-semibold">{current?.label ?? "Kometa Studio"}</h1>
          <AdvancedToggle />
          {auth.data?.signed_in && <SignOut />}
        </header>
        {auth.data && !auth.data.configured && <SignInNotice />}
        <main className="flex-1 overflow-y-auto p-4 md:p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
