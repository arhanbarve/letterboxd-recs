import { useState } from "react";

export function useLocalStorage(key, initialValue) {
  const [value, setValue] = useState(() => {
    const stored = window.localStorage.getItem(key);
    return stored !== null ? stored : initialValue;
  });

  const set = (next) => {
    setValue(next);
    window.localStorage.setItem(key, next);
  };

  return [value, set];
}
