// Feature-local civil-date arithmetic follows the existing extension convention.
// No runtime clock or Date dependency; all times are supplied by the caller.
const TIMESTAMP = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?Z$/;
const DAY_MS = 86_400_000;

function daysFromCivil(year: number, month: number, day: number): number {
  const y = month <= 2 ? year - 1 : year;
  const era = Math.floor(y / 400);
  const yoe = y - era * 400;
  const doy = Math.floor((153 * (month + (month > 2 ? -3 : 9)) + 2) / 5) + day - 1;
  const doe = yoe * 365 + Math.floor(yoe / 4) - Math.floor(yoe / 100) + doy;
  return era * 146097 + doe - 719468;
}
const MIN_TIMESTAMP_MS = daysFromCivil(0, 1, 1) * DAY_MS;
const MAX_TIMESTAMP_MS = daysFromCivil(10000, 1, 1) * DAY_MS;

/** Strict UTC to epoch milliseconds. Fractional micro/nanoseconds are truncated. */
export function parseTimestamp(value: string): number | null {
  const match = TIMESTAMP.exec(value);
  if (match === null || match[0] !== value) return null;
  const [year, month, day, hour, minute, second] = match.slice(1, 7).map(Number) as [number, number, number, number, number, number];
  const fraction = match[7] ?? "";
  const leap = (year % 4 === 0 && year % 100 !== 0) || year % 400 === 0;
  const monthDays = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1];
  if (monthDays === undefined || day < 1 || day > monthDays || hour > 23 || minute > 59 || second > 59) return null;
  const millis = Number(fraction.padEnd(3, "0").slice(0, 3));
  return ((daysFromCivil(year, month, day) * 24 + hour) * 60 + minute) * 60_000 + second * 1000 + millis;
}

/** Whole-millisecond UTC rendering, inverse of the Gregorian daysFromCivil. */
export function formatTimestamp(value: number): string {
  if (!Number.isFinite(value)) throw new RangeError("timestamp is outside the UTC protocol range");
  const ms = Math.floor(value);
  if (ms < MIN_TIMESTAMP_MS || ms >= MAX_TIMESTAMP_MS) throw new RangeError("timestamp is outside the UTC protocol range");
  const days = Math.floor(ms / DAY_MS);
  const rest = ms - days * DAY_MS;
  // Howard Hinnant's civil_from_days, matching the established pure-core approach.
  const z = days + 719468;
  const era = Math.floor(z / 146097);
  const doe = z - era * 146097;
  const yoe = Math.floor((doe - Math.floor(doe / 1460) + Math.floor(doe / 36524) - Math.floor(doe / 146096)) / 365);
  const doy = doe - (365 * yoe + Math.floor(yoe / 4) - Math.floor(yoe / 100));
  const mp = Math.floor((5 * doy + 2) / 153);
  const day = doy - Math.floor((153 * mp + 2) / 5) + 1;
  const month = mp < 10 ? mp + 3 : mp - 9;
  const year = yoe + era * 400 + (month <= 2 ? 1 : 0);
  const pad = (part: number, width = 2): string => String(part).padStart(width, "0");
  const hour = Math.floor(rest / 3_600_000);
  const minute = Math.floor((rest % 3_600_000) / 60_000);
  const second = Math.floor((rest % 60_000) / 1000);
  return `${pad(year, 4)}-${pad(month)}-${pad(day)}T${pad(hour)}:${pad(minute)}:${pad(second)}.${pad(rest % 1000, 3)}Z`;
}
