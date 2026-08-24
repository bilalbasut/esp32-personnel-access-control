import { useState, useEffect, useRef, useCallback } from 'react';

// Runs `fetchFn` immediately, then every `intervalMs`, storing whatever it
// resolves to. Guards against setting state after unmount (the same
// `isMounted` pattern the original App.jsx already used) and exposes a
// manual `refresh()` for right after a mutation (add/revoke/delete/etc.)
// instead of waiting for the next tick.
//
// fetchFn should return an object whose keys become the returned data's
// keys, e.g. `() => api.getDevices().then(devices => ({ devices }))` - this
// lets one hook call fetch several endpoints together (Dashboard needs both
// events and devices on the same cadence) while still exposing named,
// destructurable results instead of a single opaque blob.
export function usePolling(fetchFn, intervalMs = 3000) {
  const [data, setData] = useState({});
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const fetchFnRef = useRef(fetchFn);
  fetchFnRef.current = fetchFn;

  const refresh = useCallback(async () => {
    try {
      const result = await fetchFnRef.current();
      setData(result);
      setError(null);
    } catch (err) {
      setError(err.message || 'Request failed');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let isMounted = true;

    const tick = async () => {
      try {
        const result = await fetchFnRef.current();
        if (isMounted) {
          setData(result);
          setError(null);
        }
      } catch (err) {
        if (isMounted) setError(err.message || 'Request failed');
      } finally {
        if (isMounted) setLoading(false);
      }
    };

    tick();
    const id = setInterval(tick, intervalMs);
    return () => {
      isMounted = false;
      clearInterval(id);
    };
    // intervalMs intentionally omitted - changing it isn't expected at
    // runtime for any current page, and refresh() covers the manual case.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervalMs]);

  return { ...data, error, loading, refresh };
}
