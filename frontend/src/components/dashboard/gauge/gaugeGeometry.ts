/**
 * Pure geometry helpers for rendering a 270°-sweep industrial gauge.
 *
 * Angle convention: standard math degrees (0° = +x axis, increasing
 * clockwise on screen because SVG's y-axis points down). The gauge sweeps
 * from 135° (bottom-left) clockwise through 270° (top) to 405°/45°
 * (bottom-right), leaving a 90° gap centered at 90° (straight down) for
 * a digital readout.
 *
 * No function here touches JSX or Tailwind classes — this file only
 * computes numbers and path strings.
 */

export const GAUGE_START_ANGLE_DEG = 135;
export const GAUGE_END_ANGLE_DEG = 405;

export interface GaugeTick {
  value: number;
  angleDeg: number;
  isMajor: boolean;
}

export interface Point {
  x: number;
  y: number;
}

export function clampValue(value: number, min: number, max: number): number {
  if (max <= min) {
    return min;
  }

  return Math.min(Math.max(value, min), max);
}

/**
 * Maps a value in [min, max] to an angle in [startAngle, endAngle].
 * Out-of-range values are clamped rather than extrapolated past the
 * physical sweep of the dial.
 */
export function valueToAngleDeg(
  value: number,
  min: number,
  max: number,
  startAngle: number = GAUGE_START_ANGLE_DEG,
  endAngle: number = GAUGE_END_ANGLE_DEG,
): number {
  const clamped = clampValue(value, min, max);
  const fraction = max === min ? 0 : (clamped - min) / (max - min);

  return startAngle + fraction * (endAngle - startAngle);
}

export function polarToCartesian(
  centerX: number,
  centerY: number,
  radius: number,
  angleDeg: number,
): Point {
  const angleRad = (angleDeg * Math.PI) / 180;

  return {
    x: centerX + radius * Math.cos(angleRad),
    y: centerY + radius * Math.sin(angleRad),
  };
}

/**
 * Builds an SVG arc path string between startAngle and endAngle at a
 * fixed radius. Assumes a clockwise sweep of less than 360°.
 */
export function describeArcPath(
  centerX: number,
  centerY: number,
  radius: number,
  startAngle: number,
  endAngle: number,
): string {
  const start = polarToCartesian(centerX, centerY, radius, startAngle);
  const end = polarToCartesian(centerX, centerY, radius, endAngle);
  const sweepDegrees = endAngle - startAngle;
  const largeArcFlag = Math.abs(sweepDegrees) > 180 ? 1 : 0;
  const sweepFlag = 1;

  return [
    "M", start.x, start.y,
    "A", radius, radius, 0, largeArcFlag, sweepFlag, end.x, end.y,
  ].join(" ");
}

/**
 * Generates evenly spaced major ticks across [min, max], with a fixed
 * number of minor ticks subdividing each major interval.
 *
 * majorTickCount is the number of major ticks INCLUDING both ends
 * (e.g. 6 major ticks over 0-100 produces 0, 20, 40, 60, 80, 100).
 */
export function generateTicks(
  min: number,
  max: number,
  majorTickCount: number,
  minorTicksPerInterval: number,
  startAngle: number = GAUGE_START_ANGLE_DEG,
  endAngle: number = GAUGE_END_ANGLE_DEG,
): GaugeTick[] {
  if (majorTickCount < 2) {
    throw new Error("majorTickCount must be at least 2 to form an interval");
  }

  const ticks: GaugeTick[] = [];
  const majorIntervalCount = majorTickCount - 1;
  const majorStepValue = (max - min) / majorIntervalCount;

  for (let i = 0; i <= majorIntervalCount; i += 1) {
    const majorValue = min + i * majorStepValue;

    ticks.push({
      value: majorValue,
      angleDeg: valueToAngleDeg(majorValue, min, max, startAngle, endAngle),
      isMajor: true,
    });

    const isLastInterval = i === majorIntervalCount;
    if (!isLastInterval && minorTicksPerInterval > 0) {
      const minorStepValue = majorStepValue / (minorTicksPerInterval + 1);

      for (let j = 1; j <= minorTicksPerInterval; j += 1) {
        const minorValue = majorValue + j * minorStepValue;

        ticks.push({
          value: minorValue,
          angleDeg: valueToAngleDeg(minorValue, min, max, startAngle, endAngle),
          isMajor: false,
        });
      }
    }
  }

  return ticks;
}

/**
 * Determines horizontal text alignment for a tick label so labels lean
 * outward, away from the dial center, based on the cosine component of
 * the tick's angle rather than a hardcoded per-tick lookup.
 */
export function getTickTextAnchor(angleDeg: number): "start" | "middle" | "end" {
  const HORIZONTAL_ANCHOR_THRESHOLD = 0.15;
  const angleRad = (angleDeg * Math.PI) / 180;
  const cos = Math.cos(angleRad);

  if (cos < -HORIZONTAL_ANCHOR_THRESHOLD) {
    return "end";
  }

  if (cos > HORIZONTAL_ANCHOR_THRESHOLD) {
    return "start";
  }

  return "middle";
}
