import React, { Children, createContext, useContext, useEffect, useMemo, useState } from "react";

const RouterContext = createContext({
  location: "/",
  navigate: () => {},
});

function normalizePath(path) {
  if (!path) return "/";
  const normalized = path.startsWith("/") ? path : `/${path}`;
  return normalized.replace(/\/+$/, "") || "/";
}

function useRouterState() {
  const [location, setLocation] = useState(() => normalizePath(window.location.pathname));

  useEffect(() => {
    const handlePopState = () => setLocation(normalizePath(window.location.pathname));
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  const navigate = (to, { replace = false } = {}) => {
    const nextPath = normalizePath(to);
    if (nextPath === location) return;
    window.history[replace ? "replaceState" : "pushState"]({}, "", nextPath);
    setLocation(nextPath);
  };

  return useMemo(() => ({ location, navigate }), [location]);
}

export function BrowserRouter({ children }) {
  const value = useRouterState();
  return <RouterContext.Provider value={value}>{children}</RouterContext.Provider>;
}

export function Route({ element }) {
  return element || null;
}

export function Routes({ children }) {
  const { location } = useContext(RouterContext);
  const entries = Children.toArray(children);
  const matched = entries.find((child) => {
    const path = normalizePath(child.props.path || "*");
    return path === "*" || path === location;
  });
  return matched?.props.element || null;
}

export function Navigate({ to, replace = false }) {
  const { navigate } = useContext(RouterContext);
  useEffect(() => {
    navigate(to, { replace });
  }, [navigate, replace, to]);
  return null;
}

export function NavLink({ to, className, children, ...rest }) {
  const { location, navigate } = useContext(RouterContext);
  const target = normalizePath(to);
  const isActive = location === target;
  const resolvedClassName = typeof className === "function" ? className({ isActive }) : className;

  return (
    <a
      {...rest}
      href={target}
      className={resolvedClassName}
      onClick={(event) => {
        event.preventDefault();
        navigate(target);
      }}
    >
      {typeof children === "function" ? children({ isActive }) : children}
    </a>
  );
}
