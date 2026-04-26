(() => {
  const target = "/app/ops/v21/datasets/tasks";
  const shouldRedirect = window.location.pathname.startsWith("/ops");
  if (shouldRedirect) {
    window.location.replace(target);
  }
})();
