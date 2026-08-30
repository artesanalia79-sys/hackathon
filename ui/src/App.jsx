import React, { useCallback, useEffect, useRef, useState } from "react";
import { get, post, pct, usd } from "./api.js";
import IncidentCard from "./components/IncidentCard.jsx";
import IncidentList from "./components/IncidentList.jsx";
import InjectPanel from "./components/InjectPanel.jsx";
import SpeedControl from "./components/SpeedControl.jsx";
import TracePanel from "./components/TracePanel.jsx";
import TrafficPanel from "./components/TrafficPanel.jsx";

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
  const selectedRef = useRef(null);
  selectedRef.current = selected;

  const loadIncident = useCallback((id) => {
    if (!id) return;
    get(`/api/incidents/${id}`).then(setIncident);
    get(`/api/incidents/${id}/diagnosis`).then((d) => setDiagnosis(d.diagnosis));
    get(`/api/incidents/${id}/trace`).then(setTrace);
  }, []);

  useEffect(() => {
    const es = new EventSource("/api/stream");
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
            <div className="main">
              <IncidentList
                incidents={snap?.incidents || []}
                selected={selected}
                onSelect={select}
                showClosed={showClosed}
                onToggleClosed={() => setShowClosed((v) => !v)}
              />
              <div className="col scroll">
                <IncidentCard incident={incident} diagnosis={diagnosis} onAck={ack} />
              </div>
              <TracePanel trace={trace} liveSteps={liveSteps} diagnosis={diagnosis} />
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
