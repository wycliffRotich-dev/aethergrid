import {
  GAUGE_END_ANGLE_DEG,
  GAUGE_START_ANGLE_DEG,
  clampValue,
  describeArcPath,
  generateTicks,
  getTickTextAnchor,
  polarToCartesian,
  valueToAngleDeg,
} from "./gaugeGeometry";

type Props = {
  label: string;
  value: number;
  min?: number;
  max?: number;
  unit?: string;
  majorTickCount?: number;
  minorTicksPerInterval?: number;
  formatValue?: (value: number) => string;
  warningThreshold?: number;
};

const VIEWBOX_SIZE = 220;
const CENTER = 112;

const TRACK_RADIUS = 78;
const TRACK_STROKE_WIDTH = 12;
const FILL_ARC_STROKE_WIDTH = 12;

const MAJOR_TICK_OUTER_RADIUS = 94;
const MAJOR_TICK_INNER_RADIUS = 80;
const MINOR_TICK_OUTER_RADIUS = 90;
const MINOR_TICK_INNER_RADIUS = 82;
const TICK_LABEL_RADIUS = 100;

const NEEDLE_LENGTH = 70;
const NEEDLE_HUB_RADIUS = 8;

const CAPTION_OFFSET_Y = 40;
const VALUE_OFFSET_Y = 66;

function defaultFormatValue(value: number): string {
  return Math.round(value).toString();
}

export function Gauge({
  label,
  value,
  min = 0,
  max = 100,
  unit = "%",
  majorTickCount = 6,
  minorTicksPerInterval = 3,
  formatValue = defaultFormatValue,
  warningThreshold,
}: Props) {
  const clampedValue = clampValue(value, min, max);
  const isWarning =
    warningThreshold !== undefined && clampedValue >= warningThreshold;

  const ticks = generateTicks(
    min,
    max,
    majorTickCount,
    minorTicksPerInterval,
    GAUGE_START_ANGLE_DEG,
    GAUGE_END_ANGLE_DEG,
  );

  const needleAngle = valueToAngleDeg(
    clampedValue,
    min,
    max,
    GAUGE_START_ANGLE_DEG,
    GAUGE_END_ANGLE_DEG,
  );
  const needleTip = polarToCartesian(CENTER, CENTER, NEEDLE_LENGTH, needleAngle);

  const trackPath = describeArcPath(
    CENTER,
    CENTER,
    TRACK_RADIUS,
    GAUGE_START_ANGLE_DEG,
    GAUGE_END_ANGLE_DEG,
  );

  const fillArcPath = describeArcPath(
    CENTER,
    CENTER,
    TRACK_RADIUS,
    GAUGE_START_ANGLE_DEG,
    needleAngle,
  );

  const accentColorClass = isWarning ? "stroke-yellow-400" : "stroke-slate-500";
  const accentFillColorClass = isWarning ? "fill-yellow-400" : "fill-slate-200";
  const valueColorClass = isWarning ? "fill-yellow-400" : "fill-white";

  return (
    <div className="aspect-square w-full">
      <svg
        viewBox={`0 0 ${VIEWBOX_SIZE} ${VIEWBOX_SIZE}`}
        className="h-full w-full"
        role="img"
        aria-label={`${label}: ${formatValue(clampedValue)}${unit}`}
      >
        <path
          d={trackPath}
          className="fill-none stroke-slate-800"
          strokeWidth={TRACK_STROKE_WIDTH}
          strokeLinecap="butt"
        />

        <path
          d={fillArcPath}
          className={`fill-none ${accentColorClass}`}
          strokeWidth={FILL_ARC_STROKE_WIDTH}
          strokeLinecap="butt"
        />

        {ticks.map((tick) => {
          const outerRadius = tick.isMajor
            ? MAJOR_TICK_OUTER_RADIUS
            : MINOR_TICK_OUTER_RADIUS;
          const innerRadius = tick.isMajor
            ? MAJOR_TICK_INNER_RADIUS
            : MINOR_TICK_INNER_RADIUS;

          const outerPoint = polarToCartesian(CENTER, CENTER, outerRadius, tick.angleDeg);
          const innerPoint = polarToCartesian(CENTER, CENTER, innerRadius, tick.angleDeg);

          return (
            <line
              key={tick.angleDeg}
              x1={innerPoint.x}
              y1={innerPoint.y}
              x2={outerPoint.x}
              y2={outerPoint.y}
              className={tick.isMajor ? "stroke-slate-500" : "stroke-slate-700"}
              strokeWidth={tick.isMajor ? 2 : 1}
              strokeLinecap="round"
            />
          );
        })}

        {ticks
          .filter((tick) => tick.isMajor)
          .map((tick) => {
            const labelPoint = polarToCartesian(
              CENTER,
              CENTER,
              TICK_LABEL_RADIUS,
              tick.angleDeg,
            );

            return (
              <text
                key={tick.angleDeg}
                x={labelPoint.x}
                y={labelPoint.y}
                textAnchor={getTickTextAnchor(tick.angleDeg)}
                dominantBaseline="middle"
                className="fill-slate-600 font-mono"
                style={{ fontSize: 10 }}
              >
                {defaultFormatValue(tick.value)}
              </text>
            );
          })}

        <line
          x1={CENTER}
          y1={CENTER}
          x2={needleTip.x}
          y2={needleTip.y}
          className={accentColorClass}
          strokeWidth={3}
          strokeLinecap="round"
        />
        <circle
          cx={CENTER}
          cy={CENTER}
          r={NEEDLE_HUB_RADIUS}
          className={accentFillColorClass}
        />

        <text
          x={CENTER}
          y={CENTER + CAPTION_OFFSET_Y}
          textAnchor="middle"
          className="fill-slate-400 font-sans uppercase"
          style={{ fontSize: 11, letterSpacing: "0.08em" }}
        >
          {label}
        </text>
        <text
          x={CENTER}
          y={CENTER + VALUE_OFFSET_Y}
          textAnchor="middle"
          className={`font-mono font-semibold ${valueColorClass}`}
          style={{ fontSize: 28 }}
        >
          {formatValue(clampedValue)}
          {unit}
        </text>
      </svg>
    </div>
  );
}
