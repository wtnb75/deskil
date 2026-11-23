# 却下したレビュー指摘

`impl` の実装後レビューで却下した指摘の記録。1 項目 = 1 指摘で、項目 ID、レビューの種類、場所、指摘、却下の理由を書く。

## B-033

- code-review / `shared/flow/flow.py` `_state_root`: 既定の状態ディレクトリが `<cwd>/.flow/runs` から git のルートへ移り、サブディレクトリで始めた既存の run や、入れ子のリポジトリの外側のルートが対象になる。却下: B-033 の判断で「サブディレクトリの run は孤立するが一時的な状態なので許容する」と決めている。
- code-review / `find_backlog` が `.git` を手で探すので、`GIT_CEILING_DIRECTORIES` や `GIT_DIR` を見る `git rev-parse` と食い違いうる。simplify（reuse・altitude）も同じ指摘（`_git_output` の再利用、共通のルート探索）。却下: `backlog.py` と `flow.py` は別々に配布されるスクリプトで共通コードを持てない。`.git` の探索ならサブプロセスが要らず、worktree の `.git` ファイルにも対応する。
- code-review / `test_default_state_dir_is_the_git_root` が `FLOW_STATE_DIR` を消していない。却下: `test_cli.py` の autouse fixture が既に消している。
- code-review / git がない環境では状態ディレクトリがカレント基準に退避し、git がある環境で始めた run が見つからなくなる。却下: B-033 の判断が「リポジトリ外では従来どおりカレント基準へ退避」と決めている。
- simplify（efficiency）/ `_state_root` が呼び出しごとに `git rev-parse` を起動する（数 ms）。却下: 1 プロセスにつき 1 回で、手でたどる実装より worktree や ceiling の扱いが確実。
- simplify（altitude）/ `run()` が既定のファイルを `args` へ書き戻す。却下: 採用した修正で `args` を書き換えず、局所変数 `path` を使う形にした。
- 修正: simplify の `find_backlog` の単純化、`_state_root` での `_toplevel` の再利用、code-review の `lint` が絶対パスを出す点（`--file` なしでもカレントからの相対パスで出す）は採用し、修正した。

## B-041

- 自己レビュー（flow-review）/ `plugins/deskil/skills/flow-convert/flow.toml` の `fix`: `max_visits = 3` を lint の失敗・dry-run の問題・対応表への異議の 3 経路で共有するので、ユーザーの異議が多いと上限に達して `report_failed` に進む。却下: 元のスキルに上限がなく、`flow-convert` の規則どおり追加した上限で、PR に明記した。経路ごとにステートを分けると定義が長くなるだけで、害はない。
- security-review（自動）/ `shared/flow/flow.py` `_check_links`: 入れ子の git リポジトリ配下のリンクを、外側ではなくそのリポジトリで検査する。リポジトリの外のリンクを検査せずに辿る。却下: B-041 は `flow.py` に触れておらず範囲外。同じ指摘は B-038 で却下済み（下の B-038 を参照）。必要になれば別項目にする。

## B-014

- simplify（simplification）/ `shared/bench/tokens.py`: `COLUMNS` と `Stats.row()` を `as_dict()` に置き換える。`render` と JSON 出力も同じ辞書から作る。却下: 動作は変わらず、列の順序（`total` の位置）の整理も要る。好みの範囲で、テストの書き換えも増える。
- simplify（simplification）/ `collect` の 2 回目の集計ループ、`_blocks` を使う 2 つの総和、JSON 出力の `to_json` への切り出し、`--markdown` の出力: 却下: 好みの範囲で、動作は変わらない。`--markdown` は範囲外。
- simplify（reuse）/ テストの importlib の読み込みを `conftest.py` の `sys.path` + fixture に合わせる。却下: `tokens` という名前が他のモジュールとぶつかる恐れがあり、importlib のほうが安全。
- simplify（simplification）・code-review / `test_declares_python_version_for_uv_run` が先頭の文字列を固定していて、壊れやすい。`write_log` の `junk` フラグも整理できる。却下: 既存の `test_script_header.py` も同じ書き方で、他のスクリプトと揃えている。好みの範囲。
- altitude / `tool_calls` を ID で重複排除せず行ごとに数えている。却下: 1 つのブロックは 1 行にしか書かれないので現状で正しい（Claude Code のログの書き方に依存する）。
- altitude・code-review / サブエージェント（sidechain）の記録を集計に含める。却下: 範囲外。`decide` はサブエージェントを使わないので初版では影響がなく、制限を文書に書いた。
- efficiency / `cache_read` などの `getattr` による組み立て、ファイルの直列処理、テストでの再パース: 却下: ファイルごとに 1 回で、差は出ない。
- security-review: 指摘なし。
- 修正: efficiency の「ファイル全体を読み込まず 1 行ずつ読む」、code-review の「オブジェクトでない JSON の行で落ちる」「usage の値が null で落ちる」「ID のないメッセージを別の応答として数える（ID なしは除外）」、simplify の未使用の `USAGE_KEYS` の削除、`group_means` の引数の統一、`row()` の型注釈、サブエージェントを含まない制限の文書化は採用し、修正した。

## B-042

- simplify（efficiency）/ `shared/backlog/backlog.py` `remote_id_numbers`: ref ごとに `git show` を直列に最大 21 回呼ぶ。`git cat-file --batch` か `git grep` に替えるべき。却下: 1 回数 ms で、`next-id` 全体でも 0.5 秒未満。バッチにすると欠けたファイルの扱いが複雑になり、`read_backlog_ref` の再利用もできなくなる。
- simplify（reuse）/ `_git_output` が `started_ids`・`read_backlog_ref` と並ぶ 3 つ目の git 実行の薄いラッパー。共通化すべき。却下: 失敗時の扱いが違う（None を返すか `BacklogError` か）。2 つ目の呼び出し側（`started_ids`）まで触る範囲外の改修になる。`git show` の部分は `read_backlog_ref` の再利用に替えた。
- simplify（simplification）/ `next_id` の引数の型を `Iterable[int]` でなく `set[int]` にして import を外す。却下: 好みの範囲で、動作は変わらない。
- code-review・altitude / 新しい順の 20 本の上限が、マージ済みで未削除のブランチに埋まって、長く生きている PR のブランチを押し出す。却下: 上限は B-042 の判断で決めた値（件数は実装時に調整してよいとある）。`git fetch --prune` が前提で、必要になれば `--no-merged` で絞る別項目にする。
- code-review / `remote` がない、または `origin` がないリポジトリで、`--no-remote` で外せるようにすべき。却下: `origin` がなければ警告も出さず空集合を返すので、害はない。オプションを足す理由が今はない。
- altitude / `next-id` が自分で `git fetch origin` すべき。却下: 読み取りのコマンドにネットワークの副作用を足すことになる。README に「先に `git fetch`」と明記し、`add` の flow が最初に fetch する（B-043）。
- altitude / `lint --against <ref>` で origin の別項目との ID の重複を検出する。却下: B-042 の判断が別項目としている。
- security-review: 指摘なし。
- 修正: code-review の「`git show ref:path` がリポジトリルート基準で、サブディレクトリや絶対パスの `--file` で黙って失敗する」（`./` 付きの `ref_spec` で修正）、「`origin/HEAD` が未設定だとデフォルトブランチを見ない」（`origin/main`・`origin/master` を推測し、警告を出す）、「壊れた backlog のブランチで止まる」（`BacklogError` を握って読み飛ばす）、「`%(refname:short)` が曖昧になる」（完全名に変更）は採用し、修正した。simplify の再利用（`read_backlog_ref` の再利用）・単純化（`rev-parse` の削除、help を短くする、テストの共通化と弱い assertion の修正）も採用し、修正した。

## B-035

- 自己レビュー / `tests/test_deskil_dev_plugin.py` `test_triage_rejected_judge_rules`: `"twice" in prompt or "2" in prompt` の条件が緩い。却下: 文言への依存を固めすぎると、プロンプトの言い換えのたびにテストが壊れる。好みの範囲。
- flow-review・security-review: 指摘なし。

## B-028

- simplify（altitude）/ `plugins/deskil-dev/skills/decide/flow.toml` の `pick`: バッチで外した blocked 項目を伝えるのに、`--unblocked` なしの `list` との見比べをモデルに任せている。`--blocked-only` などで出すべき。却下: B-028 の判断が「`--unblocked` なしの `list` と見比べて調べる」と決めている。必要になれば別項目にする。
- simplify（altitude）/ `shared/backlog/backlog.py` `render_list`: 位置引数が増えたので、フィルターの引数をキーワード専用にまとめるべき。却下: 見た目の整理で、動作は変わらず、既存の `exclude` と同じ形。
- simplify（efficiency）/ `blocked_by` が呼ぶたびに `by_id` を作り直し、一覧が O(n²) になる。却下: 既存の挙動で、バックログの規模では差が出ない。
- simplify（simplification）/ `tests/test_backlog.py`: `ids` のラムダ（`# noqa: E731`）をモジュールの関数にまとめる。却下: 既存のテストも同じ書き方で、好みの範囲。
- simplify（simplification）/ `test_list_unblocked_drops_blocked_items_before_limit` の `limit=2` が、上限なしと同じ結果で意味がない。却下: 誤り。上限を先に適用すると B-001 と B-002 が残り、B-002 を除くと `["B-001"]` になるので、`["B-001", "B-003"]` の期待は「絞り込みの後に数える」ことを確かめている。
- code-review・simplify（reuse）・security-review: 指摘なし。
- 修正: simplify（efficiency）の「`--unblocked` のとき、行の組み立てで `blocked_by` を再び呼ぶ」は採用し、修正した。

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

## B-038

- code-review / `shared/flow/flow.py` `_expand_include`・`_localize`: `include` のパスと `cwd` は今も `posixpath.normpath` で字句的に正規化している。`lnk/../x.toml` のような include は、リンクを通した意味とずれる。却下: B-038 の判断は `{ file }` の食い違いまで。`cwd` は lint が `..` を拒否済みで食い違わない。`include` は `..` を含むパスの検査を別項目にする。
- code-review・altitude / `_check_links`: リポジトリの外にある symlink は追跡するだけで、コミット済みのリンクと比べない。却下: 実体が同じリポジトリ内にあることと、内容が `ref` と一致することは `_ref_check` が検査する。外のリンクを書き換えられる前提が要り、すり替えても同じリポジトリのコミット済みの別ファイルまでで、B-038 が許容した範囲と同じ。コメントで仕様として明記した。
- code-review / `_check_links` の 40 回の上限は、辿ったリンクの総数を数えるので、深さではない。却下: 正当な定義が 40 本を超えるリンクを通ることはなく、OS の `ELOOP` の上限（Linux 40、macOS 32）と揃えた値。
- altitude / `_check_links` が `realpath` の再実装になっている。`git archive` で `ref` を展開して実体のパスを比べる、またはリンクを辿る部分だけを generator に切り出すべき。却下: 判断（`os.readlink` で一段ずつ検査）の範囲で、`ref` の展開は実行のたびに重くなる。切り出しは動作が変わらず、好みの範囲。
- altitude / lint・include・実行時で使う「部品のパスを解決する」関数を 1 つにまとめる。却下: 範囲外の大きな改修。`{ file }` の食い違いは `..` の拒否で解消した。
- simplify（efficiency）/ 1 つのリンクの検証（`git ls-tree` と `git show`）を、同じリンクを通る include ごとに繰り返す。キャッシュや `git ls-tree -r` にまとめるべき。却下: 呼び出しは `_ref_check` の既存の形で、include の数も少なく、差は出ない。
- simplify（simplification）/ `_check_links` の中の `git` の比較を別関数に切り出す、`shown` を `os.path.relpath` にする、`hops` を `for` にする。却下: 動作が変わらず、好みの範囲。
- simplify（reuse）/ 既存の 3 つのテストが書いている `git init`・`config`・`commit` を `_commit_all` に置き換える。却下: 既存のテストの書き換えで範囲外。
- simplify（simplification）/ 2 つの新しいテストの TOML 文字列と includer の定義の共通化。却下: 既存のテストも同じ書き方で、好みの範囲。
- security-review: 指摘なし。
- 修正: code-review の「存在しない `nodir/../b.md` が lint を通り、実行時に読めない」は採用し、`{ file }` の `..` を lint で拒否する形で修正した。simplify の `_toplevel` の呼び出しを `_ref_check` の `root_top` の再利用に替える、`resolve()` を 1 回にする、不要な `("", ".")` の分岐の削除、外のリンクの扱いのコメントも採用し、修正した。
