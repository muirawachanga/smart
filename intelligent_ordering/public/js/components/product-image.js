export function productImage(url, productName, className = "smarto-product-image") {
  const fallback = () => {
    const node = document.createElement("div");
    node.className = "smarto-image-fallback";
    node.textContent = "No image";
    return node;
  };
  if (!url) return fallback();
  const image = document.createElement("img");
  image.className = className;
  image.src = url;
  image.alt = productName;
  image.loading = "lazy";
  image.addEventListener("error", () => image.replaceWith(fallback()), { once: true });
  return image;
}
