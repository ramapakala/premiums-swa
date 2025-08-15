"use client";

import { useEffect, useState } from "react";

type ClientPrincipal = {
  identityProvider: string;
  userDetails: string;
  userRoles: string[];
} | null;

export default function AuthStatus() {
  const [user, setUser] = useState<ClientPrincipal>(null);

  // IMPORTANT: Start with "/" so SSR and the FIRST client render match.
  const [redir, setRedir] = useState<string>("/");

  // After hydration, update the redirect to the full current URL.
  useEffect(() => {
    try {
      setRedir(encodeURIComponent(window.location.href));
    } catch {
      // keep "/"
    }
  }, []);

  // Fetch identity on client only (SSR renders logged-out by default).
  useEffect(() => {
    fetch("/.auth/me", { cache: "no-store" })
      .then((r) => r.json())
      .then((p) => setUser(p?.clientPrincipal ?? null))
      .catch(() => setUser(null));
  }, []);

if (!user) {
  return (
    <div className="flex gap-2">
      <a className="px-3 py-1 rounded border" href={`/.auth/login/aadb2c?post_login_redirect_uri=${redir}`}>
        Sign in / Sign up
      </a>
    </div>
  );
}

  return (
    <div className="flex items-center gap-3">
      <span className="text-sm">Hi, {user.userDetails}</span>
      <a className="px-3 py-1 rounded border" href="/.auth/logout">Logout</a>
    </div>
  );
}
