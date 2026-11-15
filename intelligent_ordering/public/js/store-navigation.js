export function initStoreNavigation() {
  const shell = document.querySelector(".ordering-shell");
  const heading = shell.querySelector(".store-page-heading");
  const breadcrumb = document.querySelector("#smarto-breadcrumb-current");
  const originalTitle = document.title;
  const originalBreadcrumb = breadcrumb?.textContent;
  const views = {
    "#admin-dashboard": ["admin", "Admin dashboard"],
    "#payment-dashboard": ["payments", "Payments"],
  };
  function updateView() {
    const view = views[window.location.hash];
    shell.dataset.storeView = view ? view[0] : "";
    heading.hidden = Boolean(view);
    document.title = view ? `${view[1]} | SmartO` : originalTitle;
    if (breadcrumb) breadcrumb.textContent = view ? view[1] : originalBreadcrumb;
  }
  updateView();
  window.addEventListener("hashchange", updateView);
}
