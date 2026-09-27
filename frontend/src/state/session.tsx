import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { SESSION_EXPIRED_EVENT } from "../api/client";
import { useMe, useUpdateProfile } from "../api/queries";
import type { User } from "../api/types";

interface SessionValue {
  user: User | null;
  loading: boolean;
  /** Куда вернуть пользователя после повторного входа (ТЗ, 4.1). */
  returnTo: string | null;
  liveUpdates: boolean;
  setLiveUpdates: (enabled: boolean) => void;
  expired: boolean;
  clearExpired: () => void;
}

const SessionContext = createContext<SessionValue | null>(null);

const LIVE_KEY = "uniflow.liveUpdates";

export function SessionProvider({ children }: { children: ReactNode }) {
  const { data: user, isLoading } = useMe();
  const updateProfile = useUpdateProfile();

  const [liveUpdates, setLiveUpdatesState] = useState<boolean>(
    () => localStorage.getItem(LIVE_KEY) !== "off",
  );
  const [expired, setExpired] = useState(false);
  const [returnTo, setReturnTo] = useState<string | null>(null);

  useEffect(() => {
    localStorage.setItem(LIVE_KEY, liveUpdates ? "on" : "off");
  }, [liveUpdates]);

  useEffect(() => {
    const onExpired = () => {
      setExpired(true);
      setReturnTo(`${window.location.pathname}${window.location.search}`);
    };
    window.addEventListener(SESSION_EXPIRED_EVENT, onExpired);
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, onExpired);
  }, []);

  const setLiveUpdates = useCallback(
    (enabled: boolean) => {
      setLiveUpdatesState(enabled);
      if (user) updateProfile.mutate({ liveUpdates: enabled });
    },
    [user, updateProfile],
  );

  const value = useMemo<SessionValue>(
    () => ({
      user: user ?? null,
      loading: isLoading,
      returnTo,
      liveUpdates,
      setLiveUpdates,
      expired,
      clearExpired: () => setExpired(false),
    }),
    [user, isLoading, returnTo, liveUpdates, setLiveUpdates, expired],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionValue {
  const context = useContext(SessionContext);
  if (!context) throw new Error("useSession вызван вне SessionProvider");
  return context;
}
