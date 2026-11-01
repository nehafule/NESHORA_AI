(() => {
  const updateCountdowns = () => {
    document.querySelectorAll("[data-countdown-target]").forEach((element) => {
      const target = new Date(element.dataset.countdownTarget);
      const remaining = target.getTime() - Date.now();
      if (Number.isNaN(target.getTime())) return;
      if (remaining <= 0) {
        const value = element.querySelector("[data-countdown-value]");
        const label = element.querySelector("[data-countdown-label]");
        if (value) value.textContent = "Now";
        if (label) label.textContent = "";
        else element.textContent = "Exam time";
        return;
      }
      const totalSeconds = Math.floor(remaining / 1000);
      const days = Math.floor(totalSeconds / 86400);
      const hours = Math.floor((totalSeconds % 86400) / 3600);
      const minutes = Math.floor((totalSeconds % 3600) / 60);
      const seconds = totalSeconds % 60;
      const text = `${days}d ${hours}h ${minutes}m ${seconds}s`;
      const value = element.querySelector("[data-countdown-value]");
      if (value) {
        value.textContent = text;
        const label = element.querySelector("[data-countdown-label]");
        if (label) label.textContent = "until exam";
      } else {
        element.textContent = text;
      }
    });
  };
  updateCountdowns();
  window.setInterval(updateCountdowns, 1000);
})();
