function dashboardChrome() {
  return {
    dark: localStorage.getItem("theme") === "dark",
    logModalOpen: false,
    init() {
      this.$watch("dark", (value) => {
        localStorage.setItem("theme", value ? "dark" : "light");
      });
    },
    toggleDark() {
      this.dark = !this.dark;
    },
    openLogModal() {
      this.logModalOpen = true;
    },
    closeLogModal() {
      this.logModalOpen = false;
    },
    refreshAll() {
      htmx.trigger(document.body, "refresh");
    },
  };
}
