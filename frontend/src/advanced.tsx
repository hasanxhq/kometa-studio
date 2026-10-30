// The arr-style "Show Advanced" switch. Forms read it to decide whether to show every option.

import { createContext, useContext, useState, type ReactNode } from "react";

const STORAGE_KEY = "studio.showAdvanced";

type Advanced = { showAdvanced: boolean; setShowAdvanced: (value: boolean) => void };

const AdvancedContext = createContext<Advanced>({ showAdvanced: false, setShowAdvanced: () => {} });

function readStored(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === "true";
  } catch {
    return false; // storage blocked (private window, previews)
  }
}

export function AdvancedProvider({ children }: { children: ReactNode }) {
  const [showAdvanced, setState] = useState(readStored);
  const setShowAdvanced = (value: boolean) => {
    setState(value);
    try {
      localStorage.setItem(STORAGE_KEY, String(value));
    } catch {
      // the choice still applies until reload
    }
  };
  return <AdvancedContext.Provider value={{ showAdvanced, setShowAdvanced }}>{children}</AdvancedContext.Provider>;
}

export const useAdvanced = () => useContext(AdvancedContext);
