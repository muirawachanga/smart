export function initStaffSidebar(hasStaffLinks) {
  const sidebar = document.querySelector("#smarto-sidebar");
  if (!sidebar) return;
  const shell = document.querySelector("#smarto-workspace-shell");
  const content = document.querySelector("#smarto-workspace-content");
  const navigation = document.querySelector("#smarto-staff-navigation");
  const toggle = document.querySelector("#smarto-sidebar-toggle");
  const close = document.querySelector("#smarto-sidebar-close");
  const collapse = document.querySelector("#smarto-sidebar-collapse");
  const backdrop = document.querySelector("#smarto-sidebar-backdrop");
  const mobile = window.matchMedia("(max-width: 850px)");
  let collapsed = false;
  let open = false;
  let active = false;

  function setOpen(value, restoreFocus = false) {
    const wasOpen = open;
    open = active && mobile.matches && value;
    shell.classList.toggle("is-sidebar-open", open);
    toggle.setAttribute("aria-expanded", String(open));
    backdrop.hidden = !open;
    content.inert = open;
    sidebar.inert = mobile.matches && !open;
    if (open) close.focus();
    else if (restoreFocus && wasOpen) toggle.focus();
  }

  function updateRoute() {
    const path = window.location.pathname.replace(/\/$/, "");
    active = hasStaffLinks && (path.startsWith("/dashboard/")
      || (path === "/store" && ["#admin-dashboard", "#payment-dashboard"].includes(window.location.hash)));
    shell.classList.toggle("has-sidebar", active);
    sidebar.hidden = !active;
    toggle.hidden = !active;
    setOpen(false);
    const links = [...navigation.querySelectorAll("a")];
    const target = `${path}${path === "/store" ? window.location.hash : ""}`;
    const current = links.find((link) => !link.hidden && link.getAttribute("href") === target);
    for (const link of links) {
      if (link === current) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    }
  }

  toggle.addEventListener("click", () => setOpen(!open));
  close.addEventListener("click", () => setOpen(false, true));
  backdrop.addEventListener("click", () => setOpen(false, true));
  collapse.addEventListener("click", () => {
    collapsed = !collapsed;
    shell.classList.toggle("is-sidebar-collapsed", collapsed);
    collapse.setAttribute("aria-expanded", String(!collapsed));
    const label = collapsed ? "Expand staff navigation" : "Collapse staff navigation";
    collapse.setAttribute("aria-label", label);
    collapse.title = label;
  });
  navigation.addEventListener("click", (event) => {
    if (event.target.closest("a")) setOpen(false, true);
  });
  document.addEventListener("keydown", (event) => {
    if (!open) return;
    if (event.key === "Escape") setOpen(false, true);
    if (event.key === "Tab") {
      const controls = [...sidebar.querySelectorAll("a, button")]
        .filter((element) => !element.hidden && element !== collapse);
      const first = controls[0];
      const last = controls.at(-1);
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
  });
  mobile.addEventListener("change", () => {
    const wasOpen = open;
    setOpen(false);
    if (wasOpen) (mobile.matches ? toggle : collapse).focus();
  });
  window.addEventListener("hashchange", updateRoute);
  updateRoute();
}
