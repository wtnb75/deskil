# 却下したレビュー指摘

`impl` の実装後レビューで却下した指摘の記録。1 項目 = 1 指摘で、項目 ID、レビューの種類、場所、指摘、却下の理由を書く。

## B-017

- code-review / `shared/flow/flow.py` `next_step`: 定義の読み込みを先にしたので、定義が変更されかつ壊れていると、`definition changed` でなく lint エラーが出る。却下: エラーの経路だけの違いで、どちらも失敗として止まる。ハッシュを先に計算するには include の解析が要り、読み込みと二重になる。
- code-review / `_expand_include`: 同じ部品を複数回 include すると、部品の lint の警告が回数分重複する。却下: 表示が重複するだけで、害はない。
- code-review / `_expand_level`: `exits` が、どこからも到達されない終了ステートも網羅する必要がある。却下: B-017 の判断が「サブの終了ステートをすべて網羅する」と決めている。
- code-review / 展開の入れ子と回数に上限がない。却下: 手書きの定義では起きず、DoS 類は対象外。必要になれば別項目にする。
- simplify（altitude）/ `_always` キー、`__` の文字列結合、`_localize` の書き換え、`sources` を引数で渡す作り: `State` ごとに `base_dir` を持たせる、型付きの状態を返す、など。却下: 範囲を超える改修で、振る舞いも変わる。今の形でテストが通り、境界も 1 か所（`_expand_level`）にまとまっている。
- simplify（reuse）/ include のパス判定を `_check_run` の書き方に揃える。却下: `a/../b` を許す字句判定は意図したもの。symlink を解決しない点が `{ file }` と違う（設計書 §6.1 に明記）。
- simplify（simplification）/ `read_toml` と `lint_raw` の薄いラッパー、`_expand_level` の引数の束ね: 却下: 既存の公開関数とテストが使っており、整理の利益が小さい。
- simplify（efficiency）/ `_ref_check` の `git show` を state ごとに繰り返す、部品の再パース: 却下: 定義の規模では数十 ms で、毎回の再検査は `--force` での差し替えを防ぐために意図したもの。
- security-review: 指摘なし（`_ref_check` の symlink 差し替えは、別の自動レビューの指摘として採用し、修正済み）。
