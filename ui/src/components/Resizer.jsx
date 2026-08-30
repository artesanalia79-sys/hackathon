import React, { useRef } from "react";

/**
 * The divider between two panels — drag to resize, double-click to fold the side
 * panel away. It lives in the 16px gutter the layout already had, so nothing moves
 * until the operator asks it to.
 */
export default function Resizer({ side, width, min, max, onResize, onToggle, label }) {
  const drag = useRef(null);
  const collapsed = width === 0;

  const clamp = (px) => Math.min(max, Math.max(min, px));
  const delta = (dx) => clamp((drag.current?.w ?? width) + (side === "left" ? dx : -dx));

  const onPointerDown = (e) => {
    if (e.button !== 0) return;
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    drag.current = { x: e.clientX, w: collapsed ? 0 : width };
    document.body.classList.add("resizing");
  };

  const onPointerMove = (e) => {
    if (!drag.current) return;
    onResize(delta(e.clientX - drag.current.x));
  };

  const endDrag = (e) => {
    if (!drag.current) return;
    drag.current = null;
    if (e.currentTarget.hasPointerCapture?.(e.pointerId)) {
      e.currentTarget.releasePointerCapture(e.pointerId);
    }
    document.body.classList.remove("resizing");
  };

  const onKeyDown = (e) => {
    const step = e.shiftKey ? 64 : 16;
    if (e.key === "ArrowLeft") { e.preventDefault(); onResize(delta(-step)); }
    else if (e.key === "ArrowRight") { e.preventDefault(); onResize(delta(step)); }
    else if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onToggle(); }
  };

  return (
    <div
      className={`resizer ${side}${collapsed ? " collapsed" : ""}`}
      role="separator"
      tabIndex={0}
      aria-label={`Resize ${label}`}
      aria-orientation="vertical"
      aria-valuenow={width}
      aria-valuemin={0}
      aria-valuemax={max}
      title={`Drag to resize · double-click to ${collapsed ? "show" : "hide"} ${label}`}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      onDoubleClick={onToggle}
      onKeyDown={onKeyDown}
    >
      <span className="grip" />
    </div>
  );
}
