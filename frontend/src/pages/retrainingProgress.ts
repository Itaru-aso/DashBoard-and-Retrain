export type Phase = "monochro" | "color";

/** tqdm進捗1件ぶんの状態（%・現在ステップ/全ステップ・loss・ETA文字列）。 */
export interface ProgressState {
  percent: number;
  current: number;
  total: number;
  loss?: number;
  eta?: string;
}

export type ClassifiedLine =
  | ({ kind: "progress" } & ProgressState & { phase?: Phase; raw: string })
  | { kind: "other"; phase?: Phase; raw: string };

const PHASE_PREFIX = /^\[(monochro|color)\]\s*/;

// tqdm既定フォーマット: "{desc}: {percent}%|{bar}| {n}/{total} [{elapsed}<{remaining}, {rate}]"
// descはtqdmが空文字のとき省略されるため任意（training/ 側のtqdm呼び出しは変更しない前提で
// 両方のパターンを受け付ける）。
const TQDM_PATTERN =
  /^(?:(?<desc>.*?):\s*)?(?<percent>\d+)%\|.*?\|\s*(?<current>\d+)\/(?<total>\d+)\s*\[(?<elapsed>[^<]*)<(?<remaining>[^,]*),\s*(?<rate>[^\]]*)\]\s*$/;

const LOSS_PATTERN = /Current loss:\s*([\d.]+)/;

/** WebSocketで受信した1行を、tqdm進捗行かそれ以外（重要ログ）かに分類する。 */
export function classifyLine(raw: string): ClassifiedLine {
  const phaseMatch = raw.match(PHASE_PREFIX);
  const phase = phaseMatch ? (phaseMatch[1] as Phase) : undefined;
  const rest = phaseMatch ? raw.slice(phaseMatch[0].length) : raw;

  const m = TQDM_PATTERN.exec(rest);
  if (!m?.groups) {
    return { kind: "other", phase, raw };
  }

  const percent = Number(m.groups.percent);
  const current = Number(m.groups.current);
  const total = Number(m.groups.total);
  if (Number.isNaN(percent) || Number.isNaN(current) || Number.isNaN(total)) {
    return { kind: "other", phase, raw };
  }

  const lossMatch = m.groups.desc?.match(LOSS_PATTERN);
  const loss = lossMatch ? Number(lossMatch[1]) : undefined;
  const eta = `${m.groups.elapsed.trim()}<${m.groups.remaining.trim()}, ${m.groups.rate.trim()}`;

  return { kind: "progress", phase, raw, percent, current, total, loss, eta };
}
