import React from "react";
import { post } from "../api.js";

const LABEL = { 0: "Pause", 1: "1×", 2: "2×", 5: "5×", 10: "10×", 30: "30×", 60: "60×" };
const HINT = {
  0: "world frozen — inspect anything without it moving",
  1: "real time: a 5-min detection window takes 5 real minutes",
  2: "5-min window in 2.5 min",
  5: "5-min window in 1 min",
  10: "5-min window in 30s — watch an incident build",
  30: "5-min window in 10s",
  60: "5-min window in 5s — fastest",
};

/**
 * Simulated time runs faster than real time so a demo is possible at all. Detection
 * windows are measured in simulated minutes, so changing this changes nothing about
 * what the engine concludes — only how long you get to watch it happen.
 */
export default function SpeedControl({ speed, options = [], onChange }) {
  return (
    <div className="speed">
      <span className="k">clock</span>
      <div className="speedbtns">
        {options.map((v) => (
          <button
            key={v}
            className={`sbtn${Number(speed) === Number(v) ? " on" : ""}${v === 0 ? " pause" : ""}`}
            title={HINT[v] || `${v}× real time`}
            onClick={async () => {
              const r = await post(`/api/speed?value=${v}`);
              onChange?.(r.sim_speed);
            }}
          >
            {LABEL[v] ?? `${v}×`}
          </button>
        ))}
      </div>
    </div>
  );
}
