import {
  Children,
  createContext,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useState,
  isValidElement,
  type AnchorHTMLAttributes,
  type ReactElement,
  type ReactNode,
} from "react";

type NavigateOptions = { replace?: boolean };
type RouterContextValue = {
  location: string;
  navigate: (to: string, options?: NavigateOptions) => void;
};
type RouterProviderProps = { children: ReactNode };
type RouteProps = { element?: ReactNode; path?: string };
type ActiveState = { isActive: boolean };
type NavLinkProps = Omit<
  AnchorHTMLAttributes<HTMLAnchorElement>,
  "children" | "className" | "href"
> & {
  children?: ReactNode | ((state: ActiveState) => ReactNode);
  className?: string | ((state: ActiveState) => string);
  to: string;
};

const RouterContext = createContext<RouterContextValue>({
  location: "/",
  navigate: () => {},
});

function normalizePath(path: string) {
  if (!path) return "/";
  const normalized = path.startsWith("/") ? path : `/${path}`;
  return normalized.replace(/\/+$/, "") || "/";
}

function useBrowserRouterState() {
  const [location, setLocation] = useState(() => normalizePath(window.location.pathname));

  useEffect(() => {
    const handlePopState = () => setLocation(normalizePath(window.location.pathname));
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  const navigate = useCallback(
    (to: string, { replace = false }: NavigateOptions = {}) => {
      const nextPath = normalizePath(to);
      if (nextPath === location) return;
      window.history[replace ? "replaceState" : "pushState"]({}, "", nextPath);
      setLocation(nextPath);
    },
    [location]
  );

  return useMemo(() => ({ location, navigate }), [location, navigate]);
}

function useMemoryRouterState(initialEntries: string[] = ["/"]) {
  const [location, setLocation] = useState(() => normalizePath(initialEntries[0] || "/"));

  const navigate = useCallback(
    (to: string) => {
      const nextPath = normalizePath(to);
      if (nextPath === location) return;
      setLocation(nextPath);
    },
    [location]
  );

  return useMemo(() => ({ location, navigate }), [location, navigate]);
}

export function BrowserRouter({ children }: RouterProviderProps) {
  const value = useBrowserRouterState();
  return <RouterContext.Provider value={value}>{children}</RouterContext.Provider>;
}

export function MemoryRouter({
  children,
  initialEntries,
}: RouterProviderProps & { initialEntries?: string[] }) {
  const value = useMemoryRouterState(initialEntries);
  return <RouterContext.Provider value={value}>{children}</RouterContext.Provider>;
}

export function Route({ element }: RouteProps) {
  return element || null;
}

export function Routes({ children }: RouterProviderProps) {
  const { location } = useContext(RouterContext);
  const entries = Children.toArray(children);
  const matched = entries.find((child): child is ReactElement<RouteProps> => {
    if (!isValidElement<RouteProps>(child)) return false;
    const routePath = child.props.path || "*";
    if (routePath === "*") return true;
    const path = normalizePath(routePath);
    return path === location;
  });
  return matched?.props.element || null;
}

export function Navigate({ to, replace = false }: { to: string; replace?: boolean }) {
  const { navigate } = useContext(RouterContext);
  useLayoutEffect(() => {
    navigate(to, { replace });
  }, [navigate, replace, to]);
  return null;
}

export function NavLink({ to, className, children, ...rest }: NavLinkProps) {
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
