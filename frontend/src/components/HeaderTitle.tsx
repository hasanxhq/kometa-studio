import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

// A page can name itself in the header (e.g. a category's own name), instead of nav.ts' generic label.
const HeaderTitleContext = createContext<{ title: string | null; setTitle: (title: string | null) => void }>({
  title: null,
  setTitle: () => {},
});

export function HeaderTitleProvider({ children }: { children: ReactNode }) {
  const [title, setTitle] = useState<string | null>(null);
  return <HeaderTitleContext.Provider value={{ title, setTitle }}>{children}</HeaderTitleContext.Provider>;
}

/** The title a page set with useHeaderTitle, or null. */
export function useHeaderTitleValue(): string | null {
  return useContext(HeaderTitleContext).title;
}

/** Show ``title`` in the header while this page is open; undefined or empty keeps nav.ts' label. */
export function useHeaderTitle(title: string | undefined) {
  const { setTitle } = useContext(HeaderTitleContext);
  useEffect(() => {
    setTitle(title || null);
    return () => setTitle(null);
  }, [title, setTitle]);
}
