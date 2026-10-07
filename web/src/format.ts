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
