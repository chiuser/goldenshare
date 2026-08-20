export const EXTREMA_LINE_LENGTH = 28;
export const EXTREMA_MIN_LINE_LENGTH = 12;
export const EXTREMA_ARROW_WING_LENGTH = 6;
export const EXTREMA_ARROW_HALF_HEIGHT = 4;
export const EXTREMA_TEXT_GAP = 8;
export const EXTREMA_EDGE_PADDING = 4;
export const EXTREMA_DIRECTION_SPLIT = 0.65;
export const EXTREMA_LINE_WIDTH = 1.5;
export const EXTREMA_FONT_SIZE = 12;

export type VisibleExtremaDirection = "extend-left" | "extend-right";

export interface VisibleExtremaMarkerLayout {
  arrowTipX: number;
  direction: VisibleExtremaDirection;
  lineEndX: number;
  lineStartX: number;
  textAlign: CanvasTextAlign;
  textX: number;
  y: number;
}

interface VisibleExtremaMarkerLayoutInput {
  anchorX: number;
  mediaWidth: number;
  textWidth: number;
  y: number;
}

export function resolveVisibleExtremaMarkerLayout({
  anchorX,
  mediaWidth,
  textWidth,
  y,
}: VisibleExtremaMarkerLayoutInput): VisibleExtremaMarkerLayout | null {
  if (
    !Number.isFinite(anchorX) ||
    !Number.isFinite(mediaWidth) ||
    !Number.isFinite(textWidth) ||
    !Number.isFinite(y) ||
    mediaWidth <= EXTREMA_EDGE_PADDING * 2 ||
    textWidth < 0
  ) {
    return null;
  }

  const leftAvailable = anchorX - EXTREMA_EDGE_PADDING;
  const rightAvailable = mediaWidth - EXTREMA_EDGE_PADDING - anchorX;
  const preferred: VisibleExtremaDirection = anchorX <= mediaWidth * EXTREMA_DIRECTION_SPLIT
    ? "extend-right"
    : "extend-left";
  const direction = resolveDirection(preferred, leftAvailable, rightAvailable, textWidth);
  if (!direction) return null;

  const available = direction === "extend-right" ? rightAvailable : leftAvailable;
  const lineLength = Math.min(
    EXTREMA_LINE_LENGTH,
    available - EXTREMA_TEXT_GAP - textWidth,
  );
  if (lineLength < EXTREMA_MIN_LINE_LENGTH) return null;

  const lineEndX = direction === "extend-right"
    ? anchorX + lineLength
    : anchorX - lineLength;

  return {
    arrowTipX: anchorX,
    direction,
    lineEndX,
    lineStartX: anchorX,
    textAlign: direction === "extend-right" ? "left" : "right",
    textX: direction === "extend-right"
      ? lineEndX + EXTREMA_TEXT_GAP
      : lineEndX - EXTREMA_TEXT_GAP,
    y,
  };
}

function resolveDirection(
  preferred: VisibleExtremaDirection,
  leftAvailable: number,
  rightAvailable: number,
  textWidth: number,
): VisibleExtremaDirection | null {
  const fullRequired = EXTREMA_LINE_LENGTH + EXTREMA_TEXT_GAP + textWidth;
  const minimumRequired = EXTREMA_MIN_LINE_LENGTH + EXTREMA_TEXT_GAP + textWidth;
  const preferredAvailable = preferred === "extend-right" ? rightAvailable : leftAvailable;
  if (preferredAvailable >= fullRequired) return preferred;

  const opposite: VisibleExtremaDirection = preferred === "extend-right"
    ? "extend-left"
    : "extend-right";
  const oppositeAvailable = opposite === "extend-right" ? rightAvailable : leftAvailable;
  if (oppositeAvailable >= fullRequired) return opposite;

  const leftFitsMinimum = leftAvailable >= minimumRequired;
  const rightFitsMinimum = rightAvailable >= minimumRequired;
  if (!leftFitsMinimum && !rightFitsMinimum) return null;
  if (!leftFitsMinimum) return "extend-right";
  if (!rightFitsMinimum) return "extend-left";
  return rightAvailable >= leftAvailable ? "extend-right" : "extend-left";
}
