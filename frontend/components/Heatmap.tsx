import type { HeatmapCell } from "../lib/types";

type HeatmapProps = {
  cells: HeatmapCell[];
};

export function Heatmap({ cells }: HeatmapProps) {
  return (
    <section className="panel">
      <div className="panelHeader">
        <div>
          <h3>Session Heatmap</h3>
          <div className="subtle">A rough operator view of when the edge tends to express.</div>
        </div>
      </div>
      <div className="list">
        {cells.map((cell) => (
          <div key={cell.label} className="listRow">
            <div className="rowTitle">
              <strong>{cell.label}</strong>
              <span className="valueUp">{(cell.value * 100).toFixed(0)}%</span>
            </div>
            <div
              style={{
                height: 8,
                borderRadius: 999,
                background: "rgba(130, 171, 210, 0.14)",
                overflow: "hidden"
              }}
            >
              <div
                style={{
                  width: `${cell.value * 100}%`,
                  height: "100%",
                  background: "linear-gradient(90deg, #2dd4bf, #f59e0b)"
                }}
              />
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

