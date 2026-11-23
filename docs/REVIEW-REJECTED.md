# 却下したレビュー指摘

`impl` の実装後レビューで却下した指摘の記録。1 項目 = 1 指摘で、項目 ID、レビューの種類、場所、指摘、却下の理由を書く。

## B-023

- code-review / `.github/workflows/ci.yml`: サードパーティの Action（`astral-sh/setup-uv@v5`、`arduino/setup-task@v2`）がコミット SHA でなくタグ固定。自動レビューも同じ指摘（MEDIUM）。却下: 具体的な攻撃経路がなく、強化策の範囲。`pull_request` トリガーで `permissions: contents: read`、シークレットは渡さず（`GITHUB_TOKEN` は読み取りのみ）、公開のリポジトリで害が限られる。SHA 固定は更新の運用（Dependabot など）とセットで別項目にする。
- security-review: 上の SHA 固定のほか、指摘なし。

## B-021

- simplify（simplification）/ `format_text` の位置指定のリストとタプル、パース処理の分割、`_format_entry`・`_trim_blank`・`main` の `fmt` 分岐・`_table_kind` の整理: 却下: 好みの範囲で、動作は変わらない。
- simplify（reuse）・code-review / 一時ファイル書き込みの共通化（`_atomic_write`）と、`_advance`・`_split_comment`・`_rewrite_ids` の字句走査の統一: 却下: `rename_state` と `save_run` を触る範囲外の改修になる。`fmt` は書き込み前後で TOML のデータの一致を確かめるので、走査の誤りは書き込みでなく拒否になる。
- code-review・altitude / `_table_kind` が、ドットを含む引用符付きのテーブル名（`[states."a.b"]`）を認識しない: 却下: ステート ID の正規表現がドットを許さないので、有効な定義では起きない。
- code-review / `splitlines()` が U+2028 などで分割する、BOM 付きのファイルで失敗する: 却下: 手書きの定義では起きず、起きても「整形できない」エラーで止まりファイルは変わらない。
- code-review / `fmt` の `os.replace` が symlink を通常のファイルに置き換え、権限を引き継がない: 却下: `rename_state` と同じ既存の方式で、`fmt` だけ変えると不揃いになる。必要になれば両方を直す別項目にする。
- code-review / 空ファイルとコメントだけのファイル、先頭コメントと最初のキーの間の空行が、整形で変わる: 却下: 判断は「キーの順序と書式をそろえる」で、空行の正規化は書式の範囲。先頭コメントは直下のキーと動く（テストで固定済み）。
- altitude / 先頭のコメントが並べ替えで `schema` と `start` の間に入る: 却下: コメントは直下のキーと一緒に動く方針で、判断の「コメントを含む行はそのまま保つ」に沿う。
- security-review: 指摘なし（`new` と `fmt` は、コマンドラインで渡されたパスだけを読み書きし、コマンドは実行しない）。

## B-020

- code-review・altitude / `stats_json`: 履歴の再生ではなく、`next` が `on_exceed` の回数を記録に残すべき。却下: B-020 の判断が「今の記録から数えられるので、記録に足す情報はない」と決めている。定義が変わった場合は、ハッシュの不一致でエラーにして対処した。
- code-review / `stats_json` と `next_step`・`dry_run` の visits の更新の重複。却下: 数行の加算で、共通化するには `dry_run` など関係のない関数を触る範囲外の改修になる。
- code-review・simplify・altitude / `--json` が `required=True` で、情報を持たない。却下: B-020 の判断が `flow stats <run-id> --json` と決めている。テキスト出力を足すときに外せる形にしてある。
- simplify（simplification）/ `step_target` の薄いラッパー。却下: 既存の呼び出し側（`dry_run`、シナリオ）を変えずに済む。
- simplify（simplification・reuse）/ テストの共通 fixture・パラメータ化・`new_run` の共通化、`next_step` と共通の定義の読み込み関数。却下: 既存のテストも、ファイルごとにヘルパーを持つ作りで、好みの範囲。
- simplify（efficiency）: 指摘なし。
- security-review: 指摘なし。

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

## B-031

- code-review / `shared/backlog/backlog.py:197` `started_ids`: PR を閉じただけでブランチが残った項目が、警告なしに除かれる。却下: ブランチの有無で判定する方針は B-031 の判断で決定済み。残ったブランチの掃除は運用側の話で、隠れた ID の表示は別項目にする。
- code-review・altitude / `started_ids`: git を `--file` のあるリポジトリでなく cwd で実行し、リモート名 `origin` も固定。却下: `impl` は常にリポジトリの中で実行し、`origin` は flow の他の手順（`origin/<default branch>`）と同じ前提。判断にも「`refs/remotes/origin/backlog/<ID>-*`」とある。
- code-review・altitude・simplify / `started_ids` の `B-\d+` が、パーサーの ID の正規表現と重複: 却下: 現状は `\d+` が `\d{3,}` の上位集合で害がなく、ID の形式を変える項目が出たときに直せばよい。
- simplify（simplification）/ `started_ids` の正規表現の二段階の処理と `getattr(exc, "stderr")`: 却下: 好みの範囲で、動作は変わらない。
- simplify・reuse / テストの `git()` ヘルパーと関数内の `import subprocess`: 却下: 既存の 2 つのテストにも同様のヘルパーがあり、共通化は関係のないテストを触る範囲外の改修になる。
- reuse / `started_ids` の `git` 呼び出しに `timeout` と `stdin=DEVNULL` がない: 却下: ローカルの ref を読むだけで、固まる経路がない。
- efficiency・altitude: 指摘なし。
- security-review: 指摘なし。

## B-016

- code-review / `render_step`: `--approval` が、ラベルの桁揃えの後ろに付くので、選択肢の行の `:` が揃わない。却下: 表示の好みで、動作は変わらない。
- code-review / `next_step`: 承認の文字列が却下（「no」など）でも進める。選択肢と承認が結びつかない。却下: B-016 の判断が「エンジンでは強制せず、記録だけ残す」と決めている。
- code-review / `flow-review`・`flow-convert` が `gate` に触れない。却下: どちらも状態キーの一覧を持たず、書き換えが要る箇所がない（`flow-author`・`flow-export` は更新済み）。

## B-012

- 自己レビュー / `shared/flow/flow.py` `export_skill`: プロンプトに `## ` で始まる行があると、出力の見出しと区別できない。却下: 手書きのプロンプトでは起きず、見出しの書式は判断で決定済み。起きたら `lint` で検出する別項目にする。
- 自己レビュー / `export_skill`: `run` の `${DEF_DIR}` を展開せず、そのまま文面に出す。却下: 展開すると絶対パスが入り、移植できない。逆変換後の文面を人が直す前提で、`dropped information` にも `run` を載せている。
- security-review: 指摘なし。

## B-018

- code-review / `export_skill`: `{{arg.x}}` を置換せずそのまま出す。却下: 判断の範囲は `start` と手順の文面への置換までで、`export` は引数を持たない（run がない）。必要になれば別項目にする。
- code-review / 部品の文面にある `{{arg.x}}` は、lint が未宣言を検査しない（実行時エラー）。却下: 部品は `[args]` を持てず、ルートの引数を参照する前提で、部品単体の lint では宣言の有無を判断できない。
- simplify: 指摘なし。
- security-review: 指摘なし（`--arg` の値は手順の文面にだけ入り、`run` の argv やファイルパスには展開しない）。
