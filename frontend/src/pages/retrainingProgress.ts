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
  | ({ kind: "progress" } & ProgressState & { phase?: Phase; raw: string; isMainLoop: boolean })
  | { kind: "other"; phase?: Phase; raw: string };

const PHASE_PREFIX = /^\[(monochro|color)\]\s*/;

// tqdmの入れ子バー（"Intermediate map normalization"等、学習ループ中に挟まる中間処理）は
// カーソル移動用のANSIエスケープ（\x1b[A）が末尾に付く。除去しないとTQDM_PATTERNに
// マッチせず other 判定になり、重要ログが埋め尽くされる。
// eslint-disable-next-line no-control-regex -- ANSI除去には制御文字\x1bのマッチが必要
const ANSI_CSI = /\x1b\[[0-9;]*[A-Za-z]/g;

// tqdm既定フォーマット: "{desc}: {percent}%|{bar}| {n}/{total} [{elapsed}<{remaining}, {rate}]"
// descはtqdmが空文字のとき省略されるため任意（training/ 側のtqdm呼び出しは変更しない前提で
// 両方のパターンを受け付ける）。
const TQDM_PATTERN =
  /^(?:(?<desc>.*?):\s*)?(?<percent>\d+)%\|.*?\|\s*(?<current>\d+)\/(?<total>\d+)\s*\[(?<elapsed>[^<]*)<(?<remaining>[^,]*),\s*(?<rate>[^\]]*)\]\s*$/;

const LOSS_PATTERN = /Current loss:\s*([\d.]+)/;

// 学習ループ本体（train_func_color.py/train_func_monochro.py の tqdm_obj.set_description）
// のdescはこの文字列で始まる。"Computing threshold scores"（学習完了直後の閾値計算）や
// "Intermediate map normalization"（学習中の中間処理）は同じtqdm形式で出力されるが、
// totalが小さくすぐ100%に達するため、学習ループ本体の進捗バーに混ぜてはならない。
const MAIN_LOOP_DESC = /^Current loss:/;

/** WebSocketで受信した1行を、tqdm進捗行かそれ以外（重要ログ）かに分類する。 */
export function classifyLine(raw: string): ClassifiedLine {
  const phaseMatch = raw.match(PHASE_PREFIX);
  const phase = phaseMatch ? (phaseMatch[1] as Phase) : undefined;
  const rest = (phaseMatch ? raw.slice(phaseMatch[0].length) : raw).replace(ANSI_CSI, "");

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

  const desc = m.groups.desc?.trim();
  const lossMatch = desc?.match(LOSS_PATTERN);
  const loss = lossMatch ? Number(lossMatch[1]) : undefined;
  const eta = `${m.groups.elapsed.trim()}<${m.groups.remaining.trim()}, ${m.groups.rate.trim()}`;
  const isMainLoop = MAIN_LOOP_DESC.test(desc ?? "");

  return { kind: "progress", phase, raw, percent, current, total, loss, eta, isMainLoop };
}

export type Stage = "backup" | "training" | "export_eval" | "completed";

export const STAGE_LABEL: Record<Stage, string> = {
  backup: "バックアップ中",
  training: "学習中",
  export_eval: "モデル出力・評価中",
  completed: "完了",
};

export const STAGE_ORDER: readonly Stage[] = ["backup", "training", "export_eval", "completed"];

// training/pipline.py・training/model_exporter.py が実際に出力するテキストをマーカーに使う
// （print文自体は変更しない）。並列学習では monochro/color どちらの開始行が来ても training
// ステージなので、複数マーカーが同一ステージを指すのは意図通り。
const STAGE_MARKERS: { stage: Stage; pattern: RegExp }[] = [
  { stage: "backup", pattern: /バックアップ作成中/ },
  {
    stage: "training",
    pattern: /(モノクロAIの学習を開始します|カラーAIの学習を開始します|並列学習 GPU 割当)/,
  },
  { stage: "export_eval", pattern: /^Exported ONNX:/ },
  { stage: "completed", pattern: /パイプライン完了/ },
];

/** 生ログ1行から検出できるジョブ全体のステージを返す（該当なしはundefined）。 */
export function detectStage(raw: string): Stage | undefined {
  for (const { stage, pattern } of STAGE_MARKERS) {
    if (pattern.test(raw)) return stage;
  }
  return undefined;
}
