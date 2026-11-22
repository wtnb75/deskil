# B-013 flow: 定義に書いたコマンドの実行と結果の受け渡し 実装計画

方針は `docs/BACKLOG.md` の B-013「判断」に従う。実装は `shared/flow/flow.py` のみ（`plugins/*/scripts/flow.py` はリンク）。

## 注意（自己改変）

この実装中の flow セッション自身が、編集中の `flow.py` で動く。

- 実行中の run JSON を壊さないよう、`Run` の新しいフィールドは `data.get(..., 既定値)` で読む。
- コマンドを持たないステートでは、git もサブプロセスも使わない。
- 各 `flow.py next` の前に `pytest` を通す。

## 定義の書式

ステートに次のキーを追加する。

| キー | 型 | 意味 |
| --- | --- | --- |
| `run` | 空でない文字列の配列 | 実行するコマンド（シェルを通さない） |
| `timeout` | 整数 >= 1 | 秒。既定 300 |
| `cwd` | 文字列（相対パス） | 定義ファイルのあるディレクトリ基準。既定は `start` を実行した場所（run に記録） |
| `output_lines` | 整数 >= 1 | 標準出力・標準エラーそれぞれの最大行数。既定 100 |

- `timeout` / `cwd` / `output_lines` は `run` がなければエラー（`option-without-run`）。
- 終了ステートに `run` は書けない（`end-with-transition` に含める）。
- `bool` は整数として受け付けない（`type(x) is int`）。

## 実行

- ステートに入るとき（`start` と `next`）に実行し、結果を `render_step` の出力へ含める。
- `Popen(start_new_session=True)`、`stdin=DEVNULL`。タイムアウト時は `os.killpg` で process group ごと止め、出力は残す。終了コードは `timeout` と表示する。
- 起動失敗（コマンドなし、権限、`cwd` なし）は、結果として報告する（例外にしない）。
- 出力は `errors="replace"` で復号し、標準出力と標準エラーを別に、末尾優先で `output_lines` 行へ切り詰める。切り捨てた行数を示す。
- 全文は `<state_dir>/<run_id>/<state>-<visit>.stdout|.stderr` に保存する（ループで上書きしない）。
- 結果（state, visit, argv, 終了コード, 切り詰め済み出力, 切り捨て行数, 保存先）を、run の `commands` リストに追加する。

## 実行の許可（`--ref`）

- `start` に `--ref REF`（既定 `main`）を追加し、run に ref 名を保存する。
- 実行の直前に毎回、定義ファイルのバイト列が `git -C <定義のディレクトリ> show REF:./<ファイル名>` と一致するかを確認する。一致したときだけ実行する（`next --force` で定義を書き換えても実行されない）。
- 一致しない、git リポジトリでない、ref がない、ファイルが ref にない場合は、実行せず、理由とコマンドを表示する（トレースバックは出さない）。
- `dry-run` は実行しない。コマンドを「未実行」として表示する。

## 作業手順

1. テストを先に書く（`tests/test_exec.py`、必要なら `test_lint_schema.py` / `test_render.py`）。git のテストは `git init -b main` で作る。
2. lint・`State`・`load_definition` を拡張する。
3. 実行処理・`Run.commands`・`--ref` を実装する。
4. `render_step` / `dry_run` に結果を載せる。
5. ドキュメント更新: `plugins/deskil/skills/flow-author/SKILL.md`、`README.md`（`start --ref`）、設計書の非ゴール行（B-013）。
6. `pytest`、`ruff` を通す。

## 範囲外

- 他のフローの `flow.toml` にコマンドを使うこと。
- 終了コードによる分岐（B-003）、承認ゲート（別項目）。
