// Runs before first paint so a saved theme never flashes the wrong colors.
try {
  const saved = JSON.parse(localStorage.getItem("shelf.theme"));
  if (saved) document.documentElement.dataset.theme = saved;
} catch (e) { /* storage blocked: follow the system theme */ }
