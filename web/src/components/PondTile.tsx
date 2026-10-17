import { memo } from "react";

import { STATUS_LABEL, TILE } from "../status";
import type { PondState, Status } from "../types";

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
      title={`${pond._id} · ${STATUS_LABEL[status]}${pond.open_incident ? ` · ${pond.open_incident}` : ""}`}
      aria-label={`${pond._id}, ${STATUS_LABEL[status]}, ${value} milligrams per litre`}
      className={`relative grid size-10 place-items-center rounded-md font-mono text-[11px] font-semibold tabular-nums ring-1 transition ${
        TILE[status]
      } ${selected ? "outline-2 outline-offset-2 outline-sky-300" : ""}`}
    >
      {value}
      {pond.open_incident && (
        <span className="absolute -right-1 -top-1 size-2.5 rounded-full bg-sky-300 ring-2 ring-night-900" aria-hidden="true" />
      )}
    </button>
  );
}

export const PondTile = memo(PondTileView);
