import { useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import type { DrumStatus, LiveDrum } from "./barograph/drum";
import type { Barograph as BarographScene } from "./barograph/scene";
import { PAPERS, PAPER_ORDER, type PaperId, type Trace } from "./barograph/papers";

interface SeriesPoint {
  t: number;
  avg: number;
}

/** A week of one Archive metric, in 10-minute steps. */
async function fetchSeries(metric: string, startTs: number, endTs: number) {
  const rows = await invoke<SeriesPoint[]>("series_window", { metric, startTs, endTs, maxPoints: 1008 });
  return rows.map((r) => ({ t: r.t, v: r.avg }));
}

const WHEN = new Intl.DateTimeFormat(undefined, {
  weekday: "long",
  day: "numeric",
  month: "long",
  hour: "numeric",
  minute: "2-digit",
});

const PAPER_KEY = "barograph.paper";

/** The paper left on the drum last time, if the browser kept it. */
function rememberedPaper(): PaperId {
  try {
    const kept = localStorage.getItem(PAPER_KEY);
    if (kept && kept in PAPERS) return kept as PaperId;
  } catch {
    // No storage: start on the pressure paper.
  }
  return "pressure";
}

const reading = (trace: Trace, value: number) => `${value.toFixed(trace.digits)} ${trace.unit}`;

/**
 * The Barograph page: the instrument drawn live, its chart inked from the
 * Archive. The drum takes a pressure, a temperature or a humidity paper, chosen
 * with the selector on the instrument or the buttons here. The dial's
 * thermometer shows `insideTemp` (degrees F), the room the instrument would
 * stand in. The 3D code loads only when this page is opened.
 */
export default function Barograph({ insideTemp }: { insideTemp?: number }) {
  const holder = useRef<HTMLDivElement>(null);
  const drumRef = useRef<LiveDrum | null>(null);
  const sceneRef = useRef<BarographScene | null>(null);
  const tempRef = useRef(insideTemp);
  const [state, setState] = useState<"loading" | "ready" | string>("loading");
  const [status, setStatus] = useState<DrumStatus | null>(null);

  const choose = (id: PaperId) => {
    drumRef.current?.setPaper(id);
    try {
      localStorage.setItem(PAPER_KEY, id);
    } catch {
      // No storage: the choice lasts until the page is left.
    }
  };

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
          onSelect: (position) => choose(PAPER_ORDER[position]),
        });
        drum = createLiveDrum(scene, sheet, fetchSeries, setStatus, rememberedPaper());
        drumRef.current = drum;
        sceneRef.current = scene;
        if (tempRef.current !== undefined) scene.setTemperature(tempRef.current);
        return () => {
          drumRef.current = null;
          sceneRef.current = null;
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

  useEffect(() => {
    tempRef.current = insideTemp;
    if (insideTemp !== undefined) sceneRef.current?.setTemperature(insideTemp);
  }, [insideTemp]);

  const paper = status && PAPERS[status.paper];

  return (
    <div className="barograph" ref={holder}>
      {state === "loading" && <p className="barograph-note barograph-centre">Setting up the barograph…</p>}
      {state !== "loading" && state !== "ready" && (
        <p className="barograph-note barograph-centre">The barograph could not be drawn: {state}</p>
      )}
      {state === "ready" && status && paper && (
        <div className="barograph-status">
          <span className="baro-papers" role="group" aria-label="Paper on the drum">
            {PAPER_ORDER.map((id) => (
              <button key={id} className={id === status.paper ? "on" : ""} aria-pressed={id === status.paper} onClick={() => choose(id)}>
                {PAPERS[id].name}
              </button>
            ))}
          </span>
          {status.changing ? (
            <span className="baro-past">Changing the paper</span>
          ) : (
            <span className={status.live ? "baro-live" : "baro-past"}>{status.live ? "Now" : "Looking back"}</span>
          )}
          <span>{WHEN.format(status.at)}</span>
          {status.live && status.value !== null && <span>{reading(paper.pen, status.value)}</span>}
          {status.live && paper.second && status.second !== null && (
            <span>
              {paper.second.name} {reading(paper.second, status.second)}
            </span>
          )}
          {status.live || status.changing ? (
            <span className="barograph-hint">Drag the drum to look back · drag elsewhere to look around</span>
          ) : (
            <button className="baro-home" onClick={() => drumRef.current?.home()}>Back to now</button>
          )}
        </div>
      )}
    </div>
  );
}
