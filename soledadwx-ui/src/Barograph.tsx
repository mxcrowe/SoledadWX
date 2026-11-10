import { useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import type { DrumStatus, LiveDrum } from "./barograph/drum";

interface SeriesPoint {
  t: number;
  avg: number;
}

/** A week of sea-level pressure from the Archive, in 10-minute steps. */
async function fetchWeek(startTs: number, endTs: number) {
  const rows = await invoke<SeriesPoint[]>("series_window", {
    metric: "baromrelin",
    startTs,
    endTs,
    maxPoints: 1008,
  });
  return rows.map((r) => ({ t: r.t, p: r.avg }));
}

const WHEN = new Intl.DateTimeFormat(undefined, {
  weekday: "long",
  day: "numeric",
  month: "long",
  hour: "numeric",
  minute: "2-digit",
});

/**
 * The Barograph page: the instrument drawn live, its chart inked from the
 * Archive. The 3D code loads only when this page is opened.
 */
export default function Barograph() {
  const holder = useRef<HTMLDivElement>(null);
  const drumRef = useRef<LiveDrum | null>(null);
  const [state, setState] = useState<"loading" | "ready" | string>("loading");
  const [status, setStatus] = useState<DrumStatus | null>(null);

  useEffect(() => {
    // A canvas of its own for each mount, so two scenes never share one.
    const canvas = document.createElement("canvas");
    holder.current!.prepend(canvas);
    let dispose: (() => void) | undefined;
    let gone = false;
    Promise.all([import("./barograph/scene"), import("./barograph/chart"), import("./barograph/drum")])
      .then(async ([{ createBarograph }, { ChartSheet }, { createLiveDrum }]) => {
        const sheet = new ChartSheet();
        let drum: LiveDrum | undefined;
        const scene = await createBarograph(canvas, {
          chart: sheet.texture,
          onDrumDrag: (hours) => drum?.drag(hours),
          onDrumRelease: () => drum?.release(),
        });
        drum = createLiveDrum(scene, sheet, fetchWeek, setStatus);
        drumRef.current = drum;
        return () => {
          drumRef.current = null;
          drum?.dispose();
          scene.dispose();
          sheet.dispose();
        };
      })
      .then(
        (made) => {
          if (gone) made();
          else {
            dispose = made;
            setState("ready");
          }
        },
        (err) => {
          if (!gone) setState(String(err));
        },
      );
    return () => {
      gone = true;
      dispose?.();
      canvas.remove();
    };
  }, []);

  return (
    <div className="barograph" ref={holder}>
      {state === "loading" && <p className="barograph-note barograph-centre">Setting up the barograph…</p>}
      {state !== "loading" && state !== "ready" && (
        <p className="barograph-note barograph-centre">The barograph could not be drawn: {state}</p>
      )}
      {state === "ready" && status && (
        <div className="barograph-status">
          <span className={status.live ? "baro-live" : "baro-past"}>{status.live ? "Now" : "Looking back"}</span>
          <span>{WHEN.format(status.at)}</span>
          {status.pressure !== null && status.live && <span>{status.pressure.toFixed(2)} inHg</span>}
          {status.live ? (
            <span className="barograph-hint">Drag the drum to look back · drag elsewhere to look around</span>
          ) : (
            <button className="baro-home" onClick={() => drumRef.current?.home()}>Back to now</button>
          )}
        </div>
      )}
    </div>
  );
}
