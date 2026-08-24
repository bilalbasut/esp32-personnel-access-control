// Small dismissible banner used by every page for "action succeeded" /
// "action failed" feedback, so that logic isn't rewritten per page.
function Alert({ variant = 'info', message, onDismiss }) {
  if (!message) return null;
  return (
    <div className={`alert alert-${variant} alert-dismissible d-flex align-items-center`} role="alert">
      <div className="flex-grow-1">{message}</div>
      {onDismiss && (
        <button type="button" className="btn-close" aria-label="Close" onClick={onDismiss}></button>
      )}
    </div>
  );
}

export default Alert;
