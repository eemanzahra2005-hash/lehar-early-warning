"use client";

import { useEffect, useState } from "react";
import { getToken } from "./api";

/** True once a bearer token is stored (read after hydration; localStorage is browser-only). */
export function useIsAdmin(): boolean {
  const [admin, setAdmin] = useState(false);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- localStorage is only readable after hydration
    setAdmin(getToken() !== null);
  }, []);
  return admin;
}
