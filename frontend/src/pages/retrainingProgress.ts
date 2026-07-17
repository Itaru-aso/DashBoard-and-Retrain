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

/** ANSIカーソル制御（\x1b[A等）を除去する。tqdm入れ子バーの残骸が表示に漏れるのを防ぐ。 */
export function stripAnsi(text: string): string {
  return text.replace(ANSI_CSI, "");
}

// tqdm既定フォーマット: "{desc}: {percent}%|{bar}| {n}/{total} [{elapsed}<{remaining}, {rate}]"
// descはtqdmが空文字のとき省略されるため任意（training/ 側のtqdm呼び出しは変更しない前提で
// 両方のパターンを受け付ける）。
// descが無いフレーム（desc未設定時の最初のtqdm出力等）はtqdmがpercentageを3桁幅で
// 右詰めするため先頭に空白パディングが入る（例: "  0%|..."）。descありの場合は
// ":\s*" が吸収するが、desc無しの場合に備えて percent の前にも "\s*" を許容する。
const TQDM_PATTERN =
  /^(?:(?<desc>.*?):\s*)?\s*(?<percent>\d+)%\|.*?\|\s*(?<current>\d+)\/(?<total>\d+)\s*\[(?<elapsed>[^<]*)<(?<remaining>[^,]*),\s*(?<rate>[^\]]*)\]\s*$/;

const LOSS_PATTERN = /Current loss:\s*([\d.]+)/;

// tqdmの最終フレームは改行を出さないため、直後の print() 出力（例: "Validation Loss: ..."）が
// \r/\n無しでそのまま連結される場合がある（実ログで観測: 学習ループの検証チェックポイント毎）。
// 分割しないとTQDM_PATTERNの末尾アンカーにマッチせず other 判定になり、重要ログに読みにくい
// 結合行が残る。
const TQDM_GLUE_SPLIT =
  /^(.*?\d+%\|.*?\|\s*\d+\/\d+\s*\[[^<]*<[^,]*,\s*[^\]]*\])([\s\S]+)$/;

/** tqdm進捗フレームに後続テキストが分離子なしで連結された行を2行に分割する（該当なしは1件配列）。 */
export function splitGluedLine(raw: string): string[] {
  const m = TQDM_GLUE_SPLIT.exec(raw);
  if (!m) return [raw];
  return [m[1], m[2]];
}

// 学習ループ本体（train_func_color.py/train_func_monochro.py の tqdm_obj.set_description）
// のdescはこの文字列で始まる。"Computing threshold scores"（学習完了直後の閾値計算）や
// "Intermediate map normalization"（学習中の中間処理）は同じtqdm形式で出力されるが、
// totalが小さくすぐ100%に達するため、学習ループ本体の進捗バーに混ぜてはならない。
const MAIN_LOOP_DESC = /^Current loss:/;

/** WebSocketで受信した1行を、tqdm進捗行かそれ以外（重要ログ）かに分類する。 */
export function classifyLine(rawInput: string): ClassifiedLine {
  // 表示に使うraw自体からもANSIを除去する（内部の判定用だけでは、重要ログ・元ログに
  // 制御文字の残骸がそのまま表示されてしまう）。
  const raw = stripAnsi(rawInput);
  const phaseMatch = raw.match(PHASE_PREFIX);
  const phase = phaseMatch ? (phaseMatch[1] as Phase) : undefined;
  const rest = phaseMatch ? raw.slice(phaseMatch[0].length) : raw;

  const m = TQDM_PATTERN.exec(rest);
  if (!m?.groups) {
    // 接頭辞([monochro]/[color])を除いた本文が無い（ANSI除去後に中身が空になった等）場合は、
    // 接頭辞だけの意味を持たない行として raw も空にする（重要ログに空の行が残らないように）。
    return { kind: "other", phase, raw: rest.trim() ? raw : "" };
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
