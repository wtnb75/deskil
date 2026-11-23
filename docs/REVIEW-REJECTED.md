# 却下したレビュー指摘

`impl` の実装後レビューで却下した指摘の記録。1 項目 = 1 指摘で、項目 ID、レビューの種類、場所、指摘、却下の理由を書く。

## B-048 / code-review / `shared/flow/flow.py:1171`

- 指摘: ハッシュに `{ file }` の本文が入るため、旧バージョンで開始した既存の run は `resume` で「definition changed」になる。ハッシュの版管理か旧ハッシュへのフォールバックが必要。
- 却下の理由: 項目の概要が「特別な移行はせず、`next` が変更を検知して `--force` を求める現状の動きに任せる」と決めている。

## B-048 / code-review / `shared/flow/flow.py:1137`

- 指摘: どの state も使わない `common` ノートのファイルまで読み込み時に読むため、読めないファイルがあると `flow runs` の全 run が `[definition changed]` になる。
- 却下の理由: 項目の判断が「すべてのファイルを同じ扱いにする」と決めている。ファイルが無い場合は従来から lint の `file-missing` で読み込みが失敗しており、新たに増えるのは UTF-8 不正など稀なケースだけ。`_definition_mark` が読み込み失敗を「changed」と表示する点は別件で、今回の範囲外。

## B-048 / code-review / `shared/flow/flow.py:2151`

- 指摘: include の有無を `sources` と `text_files` の集合の差で判定しているため、`{ file }` と部品が同じパスのとき include の警告を見落とす。
- 却下の理由: 部品は TOML、`{ file }` は prompt の本文で、同じパスを両方に使う定義は現実的でない。部品用の別フィールドを足すほどの問題ではない。
