// Runs before first paint so a saved theme never flashes the wrong colors.
try {
  const saved = JSON.parse(localStorage.getItem("bunko.theme"));
  if (saved) document.documentElement.dataset.theme = saved;
} catch {
  /* storage blocked: follow the system theme */
}
