import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";

const root = document.getElementById("root");
if (!root) throw new Error("Missing #root element");

document.body.style.margin = "0";

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
