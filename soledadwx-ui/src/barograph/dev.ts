// Stand-alone harness for the barograph scene (barograph.html, dev server only).
// It lets the scene be checked in a plain browser, with no Tauri backend.

import { createBarograph, type Barograph } from "./scene";

declare global {
  interface Window {
    barograph?: Barograph;
  }
}

const canvas = document.querySelector("canvas")!;
createBarograph(canvas).then(
  (handle) => {
    window.barograph = handle;
    document.title = "Barograph: ready";
  },
  (err) => {
    document.title = "Barograph: failed";
    document.body.append(String(err));
  },
);
