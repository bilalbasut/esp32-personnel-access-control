import { useState, useCallback } from 'react';

// Wraps "call this API function, then show success or error" - the same
// three lines (try/catch/setMessage) every button handler in this app would
// otherwise repeat. Usage:
//
//   const { status, run, dismiss } = useActionStatus();
//   const onRevoke = (uid) => run(() => api.revokeCard(uid), 'Card revoked.', refresh);
//   <Alert variant={status?.variant} message={status?.message} onDismiss={dismiss} />
export function useActionStatus() {
  const [status, setStatus] = useState(null); // { variant, message } | null

  const run = useCallback(async (action, successMessage, afterSuccess) => {
    try {
      await action();
      setStatus({ variant: 'success', message: successMessage });
      if (afterSuccess) await afterSuccess();
    } catch (err) {
      setStatus({ variant: 'danger', message: err.message || 'Something went wrong.' });
    }
  }, []);

  const dismiss = useCallback(() => setStatus(null), []);

  return { status, run, dismiss };
}
