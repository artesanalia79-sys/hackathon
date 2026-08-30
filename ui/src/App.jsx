import React, { useCallback, useEffect, useRef, useState } from "react";
import { apiUrl, get, post, pct, usd } from "./api.js";
import IncidentCard from "./components/IncidentCard.jsx";
import IncidentList from "./components/IncidentList.jsx";
import InjectPanel from "./components/InjectPanel.jsx";
import Resizer from "./components/Resizer.jsx";
import SpeedControl from "./components/SpeedControl.jsx";
import TracePanel from "./components/TracePanel.jsx";
import TrafficPanel from "./components/TrafficPanel.jsx";

// Panel widths are the operator's, not ours: they survive a reload.
const COLS_KEY = "ct.columns";
const COL_DEFAULT = { left: 330, right: 350 };
const COL_LIMITS = { left: { min: 220, max: 560 }, right: { min: 260, max: 620 } };

const readCols = () => {
  try {
    const saved = JSON.parse(localStorage.getItem(COLS_KEY));
    if (!saved || typeof saved !== "object") return COL_DEFAULT;
    return {
      ...COL_DEFAULT,
      ...saved,
      // Older versions stored a collapsed right panel as width 0. Keep the
      // operator's last real width while the drawer owns visibility now.
      right: saved.right > 0 ? saved.right : saved.rightPrev || COL_DEFAULT.right,
    };
  } catch {
    return COL_DEFAULT;
  }
};

const TABS = [
  { id: "incidents", label: "Incidents" },
  { id: "traffic", label: "Live traffic" },
  { id: "inject", label: "Inject" },
];

function NavIcon({ name }) {
  const paths = {
    incidents: (
      <>
        <path d="M4 15.5 8.5 11l3 3L20 5.5" />
        <path d="M15 5.5h5v5" />
        <path d="M4 20h16" />
      </>
    ),
    traffic: (
      <>
        <path d="M4 18V9" />
        <path d="M10 18V5" />
        <path d="M16 18v-7" />
        <path d="M22 18V3" />
      </>
    ),
    inject: (
      <>
        <path d="M12 3v12" />
        <path d="m7.5 10.5 4.5 4.5 4.5-4.5" />
        <path d="M5 18.5h14" />
      </>
    ),
  };

  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      {paths[name]}
    </svg>
  );
}

export default function App() {
  const [tab, setTab] = useState("incidents");
  const [snap, setSnap] = useState(null);
  const [catalog, setCatalog] = useState(null);
  const [speed, setSpeed] = useState(null);
  const [speedOptions, setSpeedOptions] = useState([]);
  const [selected, setSelected] = useState(null);
  const [incident, setIncident] = useState(null);
  const [diagnosis, setDiagnosis] = useState(null);
  const [trace, setTrace] = useState(null);
  const [liveSteps, setLiveSteps] = useState([]);
  const [showClosed, setShowClosed] = useState(false);
  const [cols, setCols] = useState(readCols);
  const [traceOpen, setTraceOpen] = useState(false);
  const selectedRef = useRef(null);
  selectedRef.current = selected;

  const loadIncident = useCallback((id) => {
    if (!id) return;
    get(`/api/incidents/${id}`).then(setIncident);
    get(`/api/incidents/${id}/diagnosis`).then((d) => setDiagnosis(d.diagnosis));
    get(`/api/incidents/${id}/trace`).then(setTrace);
  }, []);

  useEffect(() => {
    const es = new EventSource(apiUrl("/api/stream"));
    es.addEventListener("snapshot", (e) => setSnap(JSON.parse(e.data)));
    es.addEventListener("speed", (e) => setSpeed(JSON.parse(e.data).sim_speed));
    es.addEventListener("trace", (e) => {
      const msg = JSON.parse(e.data);
      if (msg.incident_id === selectedRef.current) setLiveSteps((prev) => [...prev, msg.step]);
    });
    es.addEventListener("diagnosis", (e) => {
      const msg = JSON.parse(e.data);
      if (msg.incident_id === selectedRef.current) loadIncident(msg.incident_id);
    });
    return () => es.close();
  }, [loadIncident]);

  useEffect(() => {
    try { localStorage.setItem(COLS_KEY, JSON.stringify(cols)); } catch { /* private mode */ }
  }, [cols]);

  const resizeCol = useCallback((side, px) => setCols((c) => ({ ...c, [side]: px })), []);
  const toggleCol = useCallback((side) => setCols((c) => ({
    ...c,
    [side]: c[side] === 0 ? c[`${side}Prev`] || COL_DEFAULT[side] : 0,
    [`${side}Prev`]: c[side] || c[`${side}Prev`] || COL_DEFAULT[side],
  })), []);

  useEffect(() => {
    get("/api/catalog").then(setCatalog);
    get("/api/speed").then((d) => { setSpeed(d.sim_speed); setSpeedOptions(d.options); });
  }, []);

  const select = (id) => {
    setSelected(id); setLiveSteps([]); setIncident(null); setDiagnosis(null); setTrace(null);
    loadIncident(id);
  };

  // A finished incident's card is history; only a live one needs refreshing.
  useEffect(() => {
    if (!selected || tab !== "incidents") return;
    const stillOpen = !incident || incident.status === "watching" || incident.status === "confirmed";
    if (!stillOpen) return;
    const t = setInterval(() => loadIncident(selected), 2500);
    return () => clearInterval(t);
  }, [selected, tab, incident, loadIncident]);

  useEffect(() => {
    if (selected || !snap?.incidents?.length) return;
    const top = snap.incidents.find((i) => i.status === "confirmed" || i.status === "watching");
    if (top) select(top.id);
  }, [snap, selected]);

  const ack = async () => {
    await post(`/api/incidents/${selected}/ack?by=ops`);
    loadIncident(selected);
  };

  const g = snap?.global;
  const below = g && g.observed_rate != null && g.observed_rate < g.expected_rate - 0.01;
  const openCount = snap?.open_count ?? 0;
  const paused = Number(speed) === 0;
  const activePage = TABS.find((item) => item.id === tab)?.label;

  return (
    <div className="app">
      <aside className="sidebar" aria-label="Primary navigation">
        <div className="brandmark" aria-label="Control Tower">
          <span>CT</span>
        </div>

        <nav className="sidenav">
          {TABS.map((item) => (
            <button
              key={item.id}
              className={`navitem${tab === item.id ? " on" : ""}`}
              onClick={() => setTab(item.id)}
              aria-current={tab === item.id ? "page" : undefined}
              aria-label={item.label}
              data-label={item.label}
            >
              <NavIcon name={item.id} />
              {item.id === "incidents" && openCount > 0 && <span className="navcount">{openCount}</span>}
            </button>
          ))}
        </nav>

        <div className={`connection${snap ? " online" : ""}`} aria-label={snap ? "Simulator connected" : "Connecting to simulator"}>
          <span />
        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div className="page-identity">
            <span className="product-name">PagoTotal · Control Tower</span>
            <strong>{activePage}</strong>
          </div>

          <div className="operational-summary">
            <div className="stat">
              <span className="k">Attempts / min</span>
              <span className="v">{g?.attempts_per_min?.toLocaleString() ?? "—"}</span>
            </div>
            <div className="stat">
              <span className="k">Conversion</span>
              <span className={`v ${below ? "bad" : "ok"}`}>{pct(g?.observed_rate)}</span>
              <span className="context">vs {pct(g?.expected_rate)} expected</span>
            </div>
            <div className="stat">
              <span className="k">Bleeding</span>
              <span className={`v ${snap?.total_cost_per_min_usd ? "warn" : ""}`}>
                {usd(snap?.total_cost_per_min_usd || 0)}/min
              </span>
            </div>
            <div className="stat simulated-clock">
              <span className="k">Simulated clock</span>
              <span className="v">
                {snap?.now ? snap.now.slice(5, 16).replace("T", " ") : "—"}
                {paused && <span className="pausedtag">paused</span>}
              </span>
            </div>
            <SpeedControl speed={speed} options={speedOptions} onChange={setSpeed} />
          </div>

          {tab !== "inject" && (
            <button className="btn primary topbar-action" onClick={() => setTab("inject")}>Inject failure</button>
          )}
        </header>

        <main className="content">
          {tab === "incidents" && (
            <div
              className={`main${cols.left === 0 ? " left-folded" : ""}${traceOpen ? " trace-open" : ""}`}
              style={{
                "--left-w": `${cols.left}px`,
                "--right-w": `${cols.right}px`,
                "--right-drawer-w": traceOpen ? `${cols.right}px` : "0px",
                "--right-drawer-gap": traceOpen ? "16px" : "0px",
              }}
            >
              {!traceOpen ? (
                <button
                  className="drawer-peek"
                  type="button"
                  aria-controls="agent-trace-drawer"
                  aria-expanded="false"
                  aria-label="Show agent trace"
                  title="Show agent trace"
                  onClick={() => setTraceOpen(true)}
                >
                  <svg className="agent-icon" aria-hidden="true" viewBox="0 0 20 20" fill="none">
                    <path d="M10 3v2M6.5 6.5h7a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-7a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2Z" />
                    <path d="M7.5 10h.01M12.5 10h.01M8 13h4" />
                  </svg>
                  <span>Agent</span>
                  <svg className="peek-chevron" aria-hidden="true" viewBox="0 0 20 20" fill="none">
                    <path d="m12 5-5 5 5 5" />
                  </svg>
                </button>
              ) : null}
              <IncidentList
                incidents={snap?.incidents || []}
                selected={selected}
                onSelect={select}
                showClosed={showClosed}
                onToggleClosed={() => setShowClosed((v) => !v)}
              />
              <Resizer
                side="left"
                label="the incident list"
                width={cols.left}
                {...COL_LIMITS.left}
                onResize={(px) => resizeCol("left", px)}
                onToggle={() => toggleCol("left")}
              />
              <div className="col scroll">
                <IncidentCard incident={incident} diagnosis={diagnosis} onAck={ack} />
              </div>
              {traceOpen ? (
                <>
                  <Resizer
                    side="right"
                    label="the agent trace"
                    width={cols.right}
                    {...COL_LIMITS.right}
                    onResize={(px) => resizeCol("right", px)}
                    onToggle={() => setTraceOpen(false)}
                  />
                  <TracePanel
                    trace={trace}
                    liveSteps={liveSteps}
                    diagnosis={diagnosis}
                    onClose={() => setTraceOpen(false)}
                  />
                </>
              ) : null}
            </div>
          )}

          {tab === "traffic" && (
            <div className="single">
              <TrafficPanel snap={snap} catalog={catalog} now={snap?.now} />
            </div>
          )}

          {tab === "inject" && (
            <div className="single scroll">
              <InjectPanel catalog={catalog} now={snap?.now} onInjected={() => setTab("incidents")} />
            </div>
          )}
        </main>
      </section>
    </div>
  );
}
