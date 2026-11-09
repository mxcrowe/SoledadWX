import { useEffect, useRef, useState } from "react";
import type { Barograph as BarographScene } from "./barograph/scene";

/**
 * The Barograph page. For now a look test: the instrument drawn live, with a
 * placeholder chart. The 3D code loads only when this page is opened.
 */
export default function Barograph() {
  const holder = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<"loading" | "ready" | string>("loading");

  useEffect(() => {
    // A canvas of its own for each mount, so two scenes never share one.
    const canvas = document.createElement("canvas");
    holder.current!.prepend(canvas);
    let scene: BarographScene | undefined;
    let gone = false;
    import("./barograph/scene")
      .then(({ createBarograph }) => createBarograph(canvas))
      .then(
        (made) => {
          if (gone) made.dispose();
          else {
            scene = made;
            setState("ready");
          }
        },
        (err) => {
          if (!gone) setState(String(err));
        },
      );
    return () => {
      gone = true;
      scene?.dispose();
      canvas.remove();
    };
  }, []);

  return (
    <div className="barograph" ref={holder}>
      {state === "loading" && <p className="barograph-note barograph-centre">Setting up the barograph…</p>}
      {state !== "loading" && state !== "ready" && (
        <p className="barograph-note barograph-centre">The barograph could not be drawn: {state}</p>
      )}
      {state === "ready" && (
        <p className="barograph-note">Look test. The trace is a placeholder, not Archive data. Drag to look around.</p>
      )}
    </div>
  );
}
