import { memo } from "react";

import { STATUS_LABEL } from "../format";
import type { PondState, Status } from "../types";

const STYLE: Record<Status, string> = {
  ok: "bg-emerald-500/15 text-emerald-200 ring-emerald-400/25 hover:bg-emerald-500/25",
  watch: "bg-amber-400/25 text-amber-100 ring-amber-300/60 hover:bg-amber-400/35",
  alert: "bg-red-500/80 text-white ring-red-300/80 alert-glow hover:bg-red-500",
  blind: "blind-hatch text-slate-400 ring-slate-500/40 hover:ring-slate-300/60",
};

interface Props {
  pond: PondState;
  status: Status;
  selected: boolean;
  onSelect: (id: string) => void;
}

function PondTileView({ pond, status, selected, onSelect }: Props) {
  const value = pond.last && status !== "blind" ? pond.last.do.toFixed(1) : "–";
  return (
    <button
      type="button"
      onClick={() => onSelect(pond._id)}
      title={`${pond._id} · ${STATUS_LABEL[status]}`}
      aria-label={`${pond._id}, ${STATUS_LABEL[status]}, ${value} milligrams per litre`}
      className={`grid size-10 place-items-center rounded-md font-mono text-[11px] font-semibold tabular-nums ring-1 transition ${
        STYLE[status]
      } ${selected ? "outline-2 outline-offset-2 outline-sky-300" : ""}`}
    >
      {value}
    </button>
  );
}

export const PondTile = memo(PondTileView);
