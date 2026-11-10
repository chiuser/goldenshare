import type { NineTurnDisplayControl } from "../controller/useNineTurnDisplayControl";

export function NineTurnIndicatorToggle({ control }: { control: NineTurnDisplayControl }) {
  return (
    <button
      aria-pressed={control.visible}
      className={`detail-chart-indicator-tab${control.visible ? " active" : ""}${control.available ? "" : " unsupported"}`}
      disabled={!control.available}
      onClick={control.available ? control.onToggle : undefined}
      type="button"
    >
      九转序列
    </button>
  );
}
