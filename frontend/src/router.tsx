// A tiny history router: enough for a single-page app with a dozen routes.
import { AnchorHTMLAttributes, MouseEvent, useEffect, useState } from "react";

export function navigate(to: string, replace = false) {
  if (to === location.pathname + location.search) return;
  if (replace) history.replaceState(null, "", to);
  else history.pushState(null, "", to);
  window.dispatchEvent(new Event("or:navigate"));
  window.scrollTo({ top: 0 });
}

export function usePath(): string {
  const [path, setPath] = useState(location.pathname);
  useEffect(() => {
    const update = () => setPath(location.pathname);
    window.addEventListener("popstate", update);
    window.addEventListener("or:navigate", update);
    return () => {
      window.removeEventListener("popstate", update);
      window.removeEventListener("or:navigate", update);
    };
  }, []);
  return path;
}

export function useQuery(): URLSearchParams {
  usePath();
  return new URLSearchParams(location.search);
}

export function match(pattern: string, path: string): Record<string, string> | null {
  const p = pattern.split("/").filter(Boolean);
  const s = path.split("/").filter(Boolean);
  if (p.length !== s.length) return null;
  const params: Record<string, string> = {};
  for (let i = 0; i < p.length; i++) {
    if (p[i].startsWith(":")) params[p[i].slice(1)] = decodeURIComponent(s[i]);
    else if (p[i] !== s[i]) return null;
  }
  return params;
}

export function Link({ to, onClick, ...rest }: AnchorHTMLAttributes<HTMLAnchorElement> & { to: string }) {
  const current = usePath();
  const active = to === "/" ? current === "/" : current === to || current.startsWith(to + "/");
  return (
    <a
      href={to}
      aria-current={active ? "page" : undefined}
      onClick={(e: MouseEvent<HTMLAnchorElement>) => {
        onClick?.(e);
        if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
        e.preventDefault();
        navigate(to);
      }}
      {...rest}
    />
  );
}
