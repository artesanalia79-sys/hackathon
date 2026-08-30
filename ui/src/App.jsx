import React, { useCallback, useEffect, useRef, useState } from "react";
import { get, post, pct, usd } from "./api.js";
import IncidentCard from "./components/IncidentCard.jsx";
import IncidentList from "./components/IncidentList.jsx";
import InjectPanel from "./components/InjectPanel.jsx";
import Sparkline from "./components/Sparkline.jsx";
import SpeedControl from "./components/SpeedControl.jsx";
import TracePanel from "./components/TracePanel.jsx";
import TrafficPanel from "./components/TrafficPanel.jsx";

const TABS = [
  { id: "incidents", label: "Incidents" },
  { id: "traffic", label: "Live traffic" },
  { id: "inject", label: "Inject" },
];

export default function App() {
  const [tab, setTab] = useState("incidents");
  const [snap, setSnap] = useState(null);
  const [health, setHealth] = useState(null);
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
    get("/health").then(setHealth);
    get("/api/catalog").then(setCatalog);
    get("/api/speed").then((d) => { setSpeed(d.sim_speed); setSpeedOptions(d.options); });
    const t = setInterval(() => get("/health").then(setHealth), 6000);
    return () => clearInterval(t);
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

  const doReset = async () => {
    await post("/api/reset");
    setSelected(null); setIncident(null); setDiagnosis(null); setTrace(null); setLiveSteps([]);
  };

  const ack = async () => {
    await post(`/api/incidents/${selected}/ack?by=ops`);
    loadIncident(selected);
  };

  const g = snap?.global;
  const below = g && g.observed_rate != null && g.observed_rate < g.expected_rate - 0.01;
  const openCount = snap?.open_count ?? 0;
  const paused = Number(speed) === 0;

  return (
    <div className="app">
      <div className="topbar">
        <div className="brand">
          <b>Control Tower</b>
          <span>PagoTotal</span>
        </div>

        <div className="stat">
          <span className="k">simulated clock</span>
          <span className="v">
            {snap?.now ? snap.now.slice(5, 16).replace("T", " ") : "—"}
            {paused && <span className="pausedtag">paused</span>}
          </span>
        </div>
        <SpeedControl speed={speed} options={speedOptions} onChange={setSpeed} />

        <div className="stat">
          <span className="k">attempts / min</span>
          <span className="v">{g?.attempts_per_min?.toLocaleString() ?? "—"}</span>
        </div>
        <div className="stat">
          <span className="k">conversion</span>
          <span className={`v ${below ? "bad" : "ok"}`}>{pct(g?.observed_rate)}</span>
          <span className="k">vs {pct(g?.expected_rate)} expected</span>
        </div>
        <div className="stat">
          <span className="k">bleeding</span>
          <span className={`v ${snap?.total_cost_per_min_usd ? "warn" : ""}`}>
            {usd(snap?.total_cost_per_min_usd || 0)}/min
          </span>
        </div>
        <div style={{ width: 150, opacity: 0.9 }}>
          <Sparkline series={g?.series} expected={g?.expected_rate} height={32} />
        </div>

        <span className="spacer" />
        <span className={`pill ${health?.agent?.available ? "live" : "off"}`}>
          {health?.agent?.available ? `agent · ${health.agent.model}` : "agent off · deterministic"}
        </span>
        <button className="btn" onClick={doReset}>Reset</button>
      </div>

      <div className="tabbar">
        {TABS.map((t) => (
          <button key={t.id} className={`tab${tab === t.id ? " on" : ""}`} onClick={() => setTab(t.id)}>
            {t.label}
            {t.id === "incidents" && openCount > 0 && <span className="count">{openCount}</span>}
          </button>
        ))}
        <span className="spacer" />
        {tab !== "inject" && (
          <button className="btn primary" onClick={() => setTab("inject")}>Inject a failure</button>
        )}
      </div>

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
    </div>
  );
}
