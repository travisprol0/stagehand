function dashboardChrome() {
  return {
    dark: localStorage.getItem("theme") === "dark",
    logModalOpen: false,
    menuOpen: false,
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
      htmx.ajax("GET", "/fragments/host-summary/", {
        target: "#host-summary",
        swap: "outerHTML",
      });
      htmx.ajax("GET", "/fragments/containers/", {
        target: "#container-table",
        swap: "outerHTML",
      });
      htmx.ajax("GET", "/fragments/runners/", {
        target: "#runner-list",
        swap: "outerHTML",
      });
      this.menuOpen = false;
    },
  };
}
