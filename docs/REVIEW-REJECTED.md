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

## B-050 / code-review / `shared/flow/flow.py:1475`

- 指摘: `os.fdopen` が失敗すると fd がリークする。`mkdir(parents=True)` の mode はリーフにしか効かず、途中の親ディレクトリが 0o755 になる。
- 却下の理由: `fdopen` が `open` 直後に失敗するのは fd 枯渇などの異常時だけで、プロセスも短命。親ディレクトリ（`.flow`）は項目が 0o700 を求めた対象（`.flow/runs` と run ディレクトリ）に入っておらず、中身は 0o700 のディレクトリが守る。

## B-050 / code-review / `shared/flow/flow.py:1495`

- 指摘: 出力の行を `\n` だけで分けるため、`\r` 区切りや改行なしの巨大な出力は 1 行として全量がメモリに載り、旧 `splitlines` と行数も変わる。
- 却下の理由: 項目の目的は終了コードと出力の保持で、メモリの上限は目的に含まれない（旧実装も全量をメモリに持っていたので悪化しない）。行の数え方は `\n` に揃える方が `tail` の感覚に合う。

## B-050 / code-review / `shared/flow/flow.py:1700`

- 指摘: 本体の終了後に残った孫プロセスが kill されず、保存先のファイルへ書き続ける。
- 却下の理由: 項目の判断が「本体の終了だけを待つ」ことで、バックグラウンドの孫が成功扱いのまま残るのが期待する動き。孫の後始末は B-055 の範囲。

## B-050 / code-review / `shared/flow/flow.py:1678`

- 指摘: コマンドの起動に失敗したとき、空の出力ファイルが残る。
- 却下の理由: 空ファイルが残るだけで、レンダリングは `error` を先に見るので表示に影響しない。存在しないコマンドが何度も起動される状況は想定しにくい。

## B-055 / code-review / `shared/flow/flow.py:1442`

- 指摘: `gc` や失敗した `start` が `.lock` ファイルを消すと、消す前にそれを開いていた別プロセスが消えた inode のロックを取り、`flock` の排他が崩れる。
- 却下の理由: `gc` は自分でロックを持ったまま消すので、その間に `next` がロックを取れず「in use」で失敗する。`gc` がロックを手放した後に消えた inode のロックを取っても、run 本体はすでにないので、ロック内の存在確認が「not found」で終わり、書き込みは起きない（この確認と `.lock` の後始末は採用した別の指摘で入れた）。

## B-049 / code-review / `shared/flow/flow.py:1977`

- 指摘: 超過回数の記録がない旧 run を `next --force` で進めると、`stats` の再生フォールバックが新しい定義で履歴を再生し、実際には起きていない超過を数える。
- 却下の理由: 項目の概要が「記録のない旧 run は、従来どおり履歴の再生にフォールバックする」と決めている。対象は修正前に開始した run だけで、時間とともに消える。

## B-049 / code-review / `shared/flow/flow.py:1390`

- 指摘: `load_run` が `exceeded` の値の型を検査しないため、手で壊した run ファイルでは `next` が `TypeError` で落ちる。
- 却下の理由: `commands` や `visits` も値の型は検査しておらず、同じ扱い。手編集した run ファイルだけの話で、通常は起きない。

## B-049 / code-review / `shared/flow/flow.py:1808`

- 指摘: `run.exceeded` の更新と保存の順序が、保存の失敗時に食い違う恐れがある。
- 却下の理由: 具体的な不具合が示されていない。`next_step` は検査をすべて通してから変更し、最後に一度だけ原子的に保存する（`save_run` は一時ファイルと置き換え）。

## B-056 / code-review / `shared/backlog/backlog.py:716`

- 指摘: 書き込み先が存在しないとき、`write_atomic` の新規ファイルの権限が umask ではなく `mkstemp` の 0600 になる。
- 却下の理由: `write_checked` が書くのは、読み込み済みの既存の docs/BACKLOG.md だけで、存在しない先へ書く経路がない。具体的な不具合を示せない。

## B-058 / code-review / `shared/flow/flow.py:747`

- 指摘: 定義のあるディレクトリ自体が symlink でリポジトリの外を指す場合や、symlink の連鎖の最終的な実体は検査しない。
- 却下の理由: 項目の概要は「include のパスの途中の symlink」の拒否で、ルートの定義ディレクトリの検査は含まない。実行対象の保証の範囲を TOML と部品に限る方針（B-046）とも合わせて、範囲外。

## B-058 / code-review / `shared/flow/flow.py:794`

- 指摘: `..` の検査が `/` 区切りだけで、Windows の `\` 区切りでは検出できない。
- 却下の理由: Windows は対象外（設計書 §3。symlink を使うため）。

## B-060 / code-review / `shared/backlog/backlog.py:771`

- 指摘: 通知する ID は `--priority` と `--unblocked` を適用する前に数えるため、それらの条件で元々表示されない着手済み項目も出る。
- 却下の理由: 通知の目的は「origin にブランチが残っている項目」を知らせることで、多めに出ても害はない。条件ごとに数え直すと `render_list` の絞り込みを二重に持つことになる。

## B-061 / code-review / `shared/backlog/backlog.py:208`

- 指摘: `--no-merged` はスカッシュマージ済みのブランチを除外できないため、このリポジトリのようにスカッシュマージして削除しない運用では、`next-id` の新しい順 20 本の枠が埋まる。バックログの内容が default と同じブランチも落とす、または `git cherry` で判定する案。
- 却下の理由: 項目の判断が「`--no-merged` に絞る」と決めている。スカッシュマージ後のブランチは `--prune` と PR 側の自動削除で消す運用で、内容比較に広げるのは別項目の話。

## B-061 / code-review, altitude / `shared/backlog/backlog.py:498`

- 指摘: `lint --against` が「ID が同じでタイトルが違う」ことを衝突の目印にしているため、既存項目のタイトルを直しただけでも指摘される。merge-base から見て「このブランチで追加した ID が origin にもある」を判定する案。
- 却下の理由: 項目の判断は「別ブランチの項目と ID が重なっていないか」の検査で、タイトルの比較はその近似として許容する。タイトルを直すのは稀で、指摘されても確認すれば済む。merge-base 方式は別項目として扱う。

## B-053 / code-review / `shared/flow/flow.py:2513`

- 指摘: 終了ステートの rename を一律に拒否するため、includer のない root 定義の終了ステートも `--allow-end` なしでは rename できない。部品かどうかを includer の探索で判定し、部品のときだけ拒否する案。
- 却下の理由: 項目の判断が「includer を探して書き換える案は、探索の範囲が未決なので採らない」と決めている。部品かどうかはファイル単体では分からないので、一律に拒否して `--allow-end` で通す形が判断の範囲。README と SKILL.md に理由を書いた。

## B-053 / code-review / `shared/flow/flow.py:2513`

- 指摘: includer を探して `exits` のキーを直す、または rename 後に includer を検証する仕組みがない。
- 却下の理由: 上と同じ。項目の判断が includer の探索と書き換えを採らないと決めている。

## B-053 / code-review / `tests/test_rename.py:51`

- 指摘: 既存のテストが `allow_end=True` で拒否を避けており、root の終了ステートを既定で rename できることを確かめるテストがない。
- 却下の理由: 既定の動きは「終了ステートは拒否」で、それを確かめる新しいテストを足した。「root は通る」は採用した動きではないので、確かめるテストは要らない。

## B-061 / code-review / `shared/backlog/backlog.py:816`

- 指摘: `--against` の ref が読めないと `BacklogError` で止まり、ローカルの lint の結果が表示されない。
- 却下の理由: 原因（ref を読めない）がエラーで明示され、ref を直せば済む。ローカルの lint は `--against` なしで実行できる。
