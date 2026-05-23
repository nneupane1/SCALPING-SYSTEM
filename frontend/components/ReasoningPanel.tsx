import type { ReasoningLine } from "../lib/types";

type ReasoningPanelProps = {
  lines: ReasoningLine[];
};

export function ReasoningPanel({ lines }: ReasoningPanelProps) {
  return (
    <section className="panel">
      <div className="panelHeader">
        <div>
          <h3>Reasoning Vector</h3>
          <div className="subtle">A human-readable trace of the rule engine.</div>
        </div>
      </div>
      <div className="list">
        {lines.map((line) => {
          const tone =
            line.status === "pass" ? "valueUp" : line.status === "block" ? "valueDown" : "";
          return (
            <div key={line.label} className="listRow">
              <div className="rowTitle">
                <strong>{line.label}</strong>
                <span className={tone}>{line.status.toUpperCase()}</span>
              </div>
              <div>{line.value}</div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

