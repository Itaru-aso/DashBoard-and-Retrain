# Seam3(training/) スコアリング統合の影響範囲レポート

ADR-6(evaluationとdeployのスコアリング実装重複の統合)実施により、
`evaluation.scoring.score_images()` の計算結果が変わる。合成フィクスチャ
(seed=0)での実測(スクリプト出力の`old=`/`new=`を転記):

| 構成 | 旧実装スコア | 新実装スコア | 備考 |
|---|---|---|---|
| A: ae_para=0, cand1無し(color相当) | 0.100000 | 0.095722 | pad+bilinear補間後にmaxを取るようになり、全color modelで恒常的なズレが解消される |
| B: ae_para=0.7(AE有効) | 0.100000 | 0.161137 | 旧実装は常にae_para=0扱いでAE項を無視していた潜在バグを解消 |
| C: monochro+cand1有効 | 0.100000 | 2.462320 | cand1コード自体が存在しなかったため、全monochroモデルでスケールが根本的に変わる |

**運用上の注意:** この修正後にrecordされるAUC/F1/miss_rate/false_alarm_rateは、
修正前の履歴データと直接比較できない(スコアのスケール・分布が変わるため)。
既存の閾値(para.jsonのthreshold)は`find_optimal_threshold`で評価時に
再計算されるため、この点は自動的に追随する。

設計書(`docs/superpowers/specs/2026-07-21-training-modular-monolith-migration-design.md`)
§5で事前承認済みの挙動変更に対応する実測レポート。
