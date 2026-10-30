// Shows the app only to a browser Studio lets in; otherwise the login page, or why it can't (handoff v2 §8).

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";

import { SIGNED_OUT_EVENT, api } from "../api";
import { Button, Field, inputClass } from "./ui";

function Centered({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-full items-center justify-center p-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 text-center font-display text-2xl font-semibold">
          Kometa <span className="text-accent">Studio</span>
        </div>
        <section className="rounded-card border border-border bg-surface p-6">{children}</section>
      </div>
    </div>
  );
}

function Login() {
  const queryClient = useQueryClient();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const login = useMutation({
    mutationFn: () => api.auth.login(username, password),
    // Everything fetched while signed out failed; start afresh.
    onSuccess: () => queryClient.resetQueries(),
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    login.mutate();
  };
  return (
    <Centered>
      <form className="flex flex-col gap-4" onSubmit={submit} aria-label="Sign in">
        <Field label="Username">
          <input className={inputClass} value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required autoFocus />
        </Field>
        <Field label="Password">
          <input
            className={inputClass}
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />
        </Field>
        {login.isError && (
          <p role="alert" className="text-sm text-err">
            {login.error.message}
          </p>
        )}
        <Button variant="primary" type="submit" disabled={login.isPending}>
          {login.isPending ? "Signing in…" : "Sign in"}
        </Button>
      </form>
    </Centered>
  );
}

export function AuthGate({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const auth = useQuery({ queryKey: ["auth"], queryFn: api.auth.status });

  useEffect(() => {
    const signedOut = () => queryClient.invalidateQueries({ queryKey: ["auth"] });
    window.addEventListener(SIGNED_OUT_EVENT, signedOut);
    return () => window.removeEventListener(SIGNED_OUT_EVENT, signedOut);
  }, [queryClient]);

  if (auth.isPending) return null;
  if (auth.isError) {
    return (
      <Centered>
        <p role="alert" className="text-err">
          Can't reach Kometa Studio: {auth.error.message}
        </p>
        <Button className="mt-4" onClick={() => auth.refetch()}>
          Try again
        </Button>
      </Centered>
    );
  }
  if (auth.data.allowed) return children;
  if (auth.data.reason === "setup") {
    return (
      <Centered>
        <h1 className="mb-2 text-base font-semibold">Sign-in isn't set up yet</h1>
        <p className="text-sm text-muted">{auth.data.message}</p>
      </Centered>
    );
  }
  return <Login />;
}
