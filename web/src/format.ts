/** Python's ``format(v, ".{p}g")`` (and ``",.{p}g"`` with ``grouping``) in TypeScript. */
export function formatG(value: number, precision = 6, grouping = false): string {
  if (value === 0) return "0";
  if (!Number.isFinite(value)) return String(value);
  const [mantissa, expPart] = value.toExponential(precision - 1).split("e");
  const exp = Number(expPart);
  if (exp < -4 || exp >= precision) {
    const m = stripZeros(mantissa);
    const sign = exp < 0 ? "-" : "+";
    return `${m}e${sign}${String(Math.abs(exp)).padStart(2, "0")}`;
  }
  const fixed = stripZeros(value.toFixed(Math.max(0, precision - 1 - exp)));
  return grouping ? group(fixed) : fixed;
}

function stripZeros(s: string): string {
  return s.includes(".") ? s.replace(/0+$/, "").replace(/\.$/, "") : s;
}

/** Result-tile format: ``sig`` significant figures, thousands grouping, exponent only when very small/large. */
export function formatSig(value: number, sig = 3): string {
  if (value === 0) return "0";
  if (!Number.isFinite(value)) return String(value);
  const a = Math.abs(value);
  if (a < 1e-4 || a >= 1e7) return formatG(value, sig);
  const decimals = sig - 1 - Math.floor(Math.log10(a));
  if (decimals >= 0) return group(stripZeros(value.toFixed(decimals)));
  const step = 10 ** -decimals;
  return group(String(Math.round(value / step) * step));
}

const PLAIN_NUMBER = /^[-+]?(\d{1,3}(,\d{3})+|\d+)?(\.\d+)?(e[-+]?\d+)?$/i;

/** Re-format a value that is a bare number (string or number) with `formatSig`; other text unchanged. */
export function tidyNumber<T>(value: T, sig = 3): T | string {
  if (typeof value === "number") return formatSig(value, sig);
  if (typeof value !== "string") return value;
  const s = value.trim();
  if (!/\d/.test(s) || !PLAIN_NUMBER.test(s)) return value;
  const x = Number(s.replace(/,/g, ""));
  return Number.isFinite(x) ? formatSig(x, sig) : value;
}

function group(s: string): string {
  const [int, frac] = s.split(".");
  const sign = int.startsWith("-") ? "-" : "";
  const digits = sign ? int.slice(1) : int;
  const grouped = digits.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return sign + grouped + (frac !== undefined ? `.${frac}` : "");
}

/** Unit Converter display format (pages/unit_converter.py ``_fmt``). */
export function formatConverted(value: number | null): string {
  if (value === null) return "—";
  if (value === 0) return "0";
  const a = Math.abs(value);
  return a < 1e-4 || a >= 1e8 ? formatG(value, 6) : formatG(value, 6, true);
}

/** Python ``f"{v:.{d}f}"``; "—" for missing values. */
export function formatF(value: unknown, digits: number): string {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "—";
}

/** Python ``f"{v:.{d}e}"`` (two-digit exponent, e.g. 2.300e-09); "—" for missing values. */
export function formatE(value: unknown, digits: number): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  const [m, e] = value.toExponential(digits).split("e");
  const exp = Number(e);
  return `${m}e${exp < 0 ? "-" : "+"}${String(Math.abs(exp)).padStart(2, "0")}`;
}
