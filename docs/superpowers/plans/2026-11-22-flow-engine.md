# フローエンジン 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 手順書型 skill を TOML のステートマシンとして定義し、現在のステップだけを出力する CLI（`flow.py`）と、構造を検査する linter、作成・レビュー支援の core プラグインを作る。

**Architecture:** エンジンは標準ライブラリだけの単一ファイル `shared/flow/flow.py`。定義は読み取り専用の TOML、実行状態は作業ディレクトリの `.flow/runs/<run-id>.json`。lint は生の dict に対して動き、load / render / run / dry-run / rename はそれを土台にする。feature と core へは相対 symlink で同梱する。

**Tech Stack:** Python 3.11+（標準ライブラリのみ）、`uv run`、pytest、ruff、go-task。

**Spec:** `docs/superpowers/specs/2026-11-22-flow-engine-design.md`（以下「設計書」。節番号は設計書のもの）

## Global Constraints

- Python 3.11 以上、**標準ライブラリのみ**。`uv run` で実行できること。（設計書 §3）
- エンジンは**単一ファイル** `flow.py`。feature プラグインへ symlink で同梱する。（§3）
- エンジンはプラグイン外のファイルに依存しない。ユーザーの設定ファイルを書き換えない。（§3）
- 状態は作業ディレクトリ側の `.flow/runs/<run-id>.json`。プラグインのキャッシュには書かない。（§3, §7）
- Windows は対象外。（§3）
- ステート ID は `^[A-Za-z_][A-Za-z0-9_]*$`、判定ラベルは `^[A-Za-z0-9_]+$`。（§6）
- 予約キー `delegate` の使用と、未知のキーは lint エラー。（§6, §9）
- `max_visits`: 入った回数が上限に達していたら、次の入場は `on_exceed` へ移る。（§12）
- 定義が変わった run は、ハッシュ不一致で `next` を拒否し、`--force` で続行できる。（§12）
- コード内のコメント、ログ、エラーメッセージ、`README.md`、`flow.py` が出力する定型文（`Notes:` など）、`SKILL.md` と移行例の定義・プロンプトは**英語**。`docs/` 配下のドキュメントは日本語。
- ツールは `uv` / `pytest` / `ruff` / `task` を使う。テスト実行は `uv run --with pytest pytest tests -q`。

## Review Focus

設計書が暗に求めていて、どのタスクの機能テストでも直接は扱わない入力を挙げる。各行のテストは、担当タスクの末尾（`Review Focus` ステップ）に入れてある。

1. TOML の構文エラーを含む定義 → スタックトレースではなく、パスと行番号つきの 1 行エラー（Task 1）。
2. `--result` の綴り違い・大文字違い（`XXX`）→ 状態を変えず、選べるラベルを再掲（Task 6）。
3. 終了済み run への `next`、存在しない run-id → 分かるエラー（Task 6）。
4. run の開始後に定義ファイルが消えた / 書き換わった → 分かるエラー、`--force` の挙動（Task 6）。
5. 別のディレクトリから `flow next` を実行 → 「run が見つからない（探した場所）」を示すエラー（Task 7）。

## ファイル構成

```
shared/flow/flow.py              エンジン本体（単一ファイル）
tests/conftest.py                flow.py の import と共通フィクスチャ
tests/test_*.py                  タスクごとのテスト
Taskfile.yml                     task test / task lint
plugins/feature-a/scripts/flow.py             → ../../../shared/flow/flow.py（symlink）
plugins/feature-a/skills/review-loop/{SKILL.md,flow.toml}   移行例
plugins/core/                    作成・レビュー支援 skill（flow-author, flow-review）
```

`flow.py` は、次の順にセクションを分ける（後続タスクは同じファイルに追記する）: errors → read/lint → load/text → render → runs → dry-run → rename → CLI。

---

### Task 1: 土台と TOML 読み込み

**Files:**
- Create: `shared/flow/flow.py`, `tests/conftest.py`, `tests/test_read.py`, `Taskfile.yml`

**Interfaces:**
- Produces:
  - `class FlowError(Exception)`
  - `@dataclass(frozen=True) class Issue: level: str; code: str; where: str; message: str`（`level` は `"error"` / `"warning"`）
  - `def read_toml(path: Path) -> dict`（I/O エラー・構文エラーは `FlowError`）
  - conftest のフィクスチャ `write_def(tmp_path, text) -> Path`（`flow.toml` を書いてパスを返す）と、`flow` モジュール（`shared/flow` を `sys.path` に足して import）

- [ ] **Step 1: 失敗するテストを書く** — `tests/test_read.py`:
  - `test_read_toml_ok`: `start = "a"` を書いて `read_toml(p) == {"start": "a"}`
  - `test_read_toml_syntax_error_has_path_and_line`（Review Focus 1）: `start = ` のような壊れた TOML で `FlowError` が出て、`str(e)` にファイルパスと `"line"` が含まれ、`TOMLDecodeError` が漏れない
  - `test_read_toml_missing_file`: 存在しないパスで `FlowError`
- [ ] **Step 2: 実行して失敗を確認** — `uv run --with pytest pytest tests -q`（期待: import エラーまたは未定義で FAIL）
- [ ] **Step 3: 実装** — 上記 3 つを `flow.py` に実装する。`tomllib` の `TOMLDecodeError` を `FlowError(f"{path}: {e}")` に包む。`Taskfile.yml` に `test`（上記 pytest コマンド）と `lint`（`uv run --with ruff ruff check .`）を定義する。
- [ ] **Step 4: 実行して成功を確認** — 期待: 3 passed。`task test` と `task lint` も通る。
- [ ] **Step 5: Commit** — `git add shared tests Taskfile.yml && git commit -m "feat(flow): add skeleton and TOML reader"`

---

### Task 2: linter（構造・スキーマの検査）

**Files:**
- Modify: `shared/flow/flow.py`
- Test: `tests/test_lint_schema.py`

**Interfaces:**
- Consumes: `Issue`（Task 1）
- Produces: `def lint_schema(raw: dict, base_dir: Path) -> list[Issue]`（`raw` は `tomllib` が返した dict。例外は投げず、不正な型も Issue にする）

**検査コード（`Issue.code`）**: すべて `level="error"` で、`where` は `states.s2.choices[0]` のような位置を指す。

| code | 条件 |
|---|---|
| `schema` | `schema` がない、または `1` 以外 |
| `start` | `start` がない、または `states` に存在しない |
| `unknown-key` | 許可キー以外（トップ: `schema,start,notes,states` / notes: `always,common` / state: `prompt,notes,goto,choices,end,max_visits,on_exceed` / choice: `label,when,goto`） |
| `reserved-key` | `delegate` を使用（`unknown-key` ではなくこちらを出す） |
| `type` | 型が違う（例: `states` が table でない、`notes` が list でない） |
| `id-format` | ステート ID が `^[A-Za-z_][A-Za-z0-9_]*$` に合わない |
| `label-format` | `label` が `^[A-Za-z0-9_]+$` に合わない |
| `missing-target` | `goto` / `on_exceed` の宛先が存在しない |
| `transition-count` | `goto` / `choices` / `end` が 0 個、または 2 個以上 |
| `end-with-transition` | `end = true` に `goto` / `choices` / `max_visits` がある |
| `label-duplicate` | 同じステート内で `label` が重複 |
| `when-missing` | `choices` の要素に `when` がない |
| `on-exceed-missing` | `max_visits` があるのに `on_exceed` がない |
| `prompt-missing` | `prompt` がない |
| `file-missing` | `{ file = ... }` のファイルが存在しない |
| `file-outside` | `{ file }` が絶対パス、または `..` で `base_dir` の外へ出る |
| `note-undefined` | ステートの `notes` が `notes.common` に定義されていない |

- [ ] **Step 1: 失敗するテストを書く** — 最小の正しい定義（`start` + 2 ステート）を返すヘルパーを `tests/test_lint_schema.py` に置き、`test_valid_definition_has_no_issues` で `lint_schema(...) == []` を確認する。続いて `test_schema_errors` を、上表の各 code につき 1 行の `(定義テキスト, 期待 code)` で parametrize する（`reserved-key` の行は `delegate = "x"` を含む定義で、`unknown-key` が出ないことも assert する）。`test_file_outside` は `{ file = "../x.md" }` と絶対パスの 2 行。`test_issue_where_points_at_state`: `prompt-missing` の `where` が `"states.s2"` を含む。
- [ ] **Step 2: 失敗を確認** — `uv run --with pytest pytest tests/test_lint_schema.py -q`
- [ ] **Step 3: 実装** — `lint_schema` を実装する。テキスト値の検査は共通ヘルパー `_check_text(value, where, base_dir, issues)`（文字列 / `{ file }` のみ許可。`file` は `base_dir` からの相対で解決し、`resolve()` した結果が `base_dir` 配下かで `file-outside` を判定）にまとめる。
- [ ] **Step 4: 成功を確認** — 同じコマンド。全体の `task test` も通す。
- [ ] **Step 5: Commit** — `git commit -m "feat(flow): add schema linter"`

---

### Task 3: linter（グラフの検査と警告）

**Files:**
- Modify: `shared/flow/flow.py`
- Test: `tests/test_lint_graph.py`

**Interfaces:**
- Consumes: `lint_schema`（Task 2）
- Produces:
  - `def lint_graph(raw: dict) -> list[Issue]`（`lint_schema` がエラーを返さない定義だけが対象）
  - `def lint(path: Path) -> list[Issue]`（`read_toml` → `lint_schema` → エラーがなければ `lint_graph`。`read_toml` の `FlowError` はそのまま送出）

**検査コード**

| code | level | 条件 |
|---|---|---|
| `orphan` | error | `start` から到達できないステート |
| `dead-end` | error | `start` から到達できるが、`end` ステートへ到達できないステート（`on_exceed` の辺も含めて判定） |
| `unused-note` | warning | どのステートからも参照されない `notes.common` のキー |
| `single-choice` | warning | 要素が 1 つだけの `choices` |
| `unbounded-loop` | warning | 循環のうち、`max_visits` を持つステートを 1 つも含まないもの |

- [ ] **Step 1: 失敗するテストを書く** — `test_orphan`（`s9` に誰も遷移しない）、`test_dead_end_cycle`（`a -> b -> a` で `end` に出口がない）、`test_dead_end_via_on_exceed_is_ok`（循環に出口が `on_exceed` だけでも、`end` へ着けば error なし）、`test_unused_note_warning`、`test_single_choice_warning`、`test_unbounded_loop_warning`（`max_visits` なしの循環）、`test_bounded_loop_no_warning`、`test_lint_skips_graph_when_schema_errors`（スキーマエラーがあるとき `orphan` は出ない）、`test_lint_returns_toml_error`（構文エラーは `FlowError`）。
- [ ] **Step 2: 失敗を確認**
- [ ] **Step 3: 実装** — 辺は `goto` / 各 `choices[].goto` / `on_exceed`。到達性は `start` からの BFS、`dead-end` は `end` ステートからの逆向き BFS。`unbounded-loop` は強連結成分（Tarjan か、各ノードから自分へ戻れるかの DFS）で、要素が 2 以上、または自己ループの成分を循環とみなす。
- [ ] **Step 4: 成功を確認**
- [ ] **Step 5: Commit** — `git commit -m "feat(flow): add graph linter"`

---

### Task 4: 定義の読み込みとテキスト値

**Files:**
- Modify: `shared/flow/flow.py`
- Test: `tests/test_load.py`

**Interfaces:**
- Consumes: `lint`（Task 3）
- Produces:
  - `Text = str | dict`（生の値。`{"file": "..."}` の dict も含む）
  - `@dataclass(frozen=True) class Choice: label: str; when: Text; goto: str`
  - `@dataclass(frozen=True) class State: id: str; prompt: Text; notes: tuple[str, ...]; goto: str | None; choices: tuple[Choice, ...]; end: bool; max_visits: int | None; on_exceed: str | None`
  - `@dataclass(frozen=True) class Definition: path: Path; base_dir: Path; start: str; always: tuple[Text, ...]; common: dict[str, Text]; states: dict[str, State]`
  - `def load_definition(path: Path) -> Definition`（lint の error が 1 つでもあれば、全 Issue を整形した `FlowError`）
  - `def read_text_value(value: Text, base_dir: Path) -> str`（文字列はそのまま。`{file}` は UTF-8 で読み、末尾の改行を 1 つ取り除く。失敗は `FlowError`）

- [ ] **Step 1: 失敗するテストを書く** — `test_load_builds_definition`（設計書 §6 の例で `start`、`states["s3"].max_visits == 2`、`choices[0].label == "xxx"`）、`test_load_rejects_lint_errors`（`FlowError` のメッセージに `unknown-key` などの code が含まれる）、`test_read_text_value_inline`、`test_read_text_value_file_strips_one_trailing_newline`、`test_read_text_value_missing_file_raises`、`test_read_text_value_not_utf8_raises`（`FlowError`、`UnicodeDecodeError` が漏れない）。
- [ ] **Step 2: 失敗を確認**
- [ ] **Step 3: 実装** — `load_definition` は `lint` の結果にエラーがあれば `FlowError`、なければ dict からデータクラスを組み立てる。`Definition.path` は絶対パスに解決する。
- [ ] **Step 4: 成功を確認**
- [ ] **Step 5: Commit** — `git commit -m "feat(flow): add definition loader and text values"`

---

### Task 5: ステップの出力（render）

**Files:**
- Modify: `shared/flow/flow.py`
- Test: `tests/test_render.py`

**Interfaces:**
- Consumes: `Definition`, `State`, `read_text_value`（Task 4）
- Produces: `def render_step(defn: Definition, state_id: str, run_id: str, cmd: str = "flow") -> str`（`cmd` は `next` コマンドの接頭辞）

**出力形式（設計書 §8）**: 末尾に改行 1 つ。

```
[s1_1] (run: R1)
<prompt text>

Notes:
- <each always entry>
- <each referenced common entry>

After finishing the work, report the result with one of the following:
  flow next R1 --result xxx   : <when>
  flow next R1 --result other : <when>
```

- 注意書きは `always`（定義順）→ ステートの `notes`（参照順）。重複は 1 回にする。0 件なら `Notes:` の節ごと省く。
- ラベルは最長のものに合わせて左揃えで桁をそろえる。
- 分岐なし: 末尾が `After finishing the work, run:` と `  flow next R1`。
- `end`: 末尾が `Flow complete.`（`next` の案内なし）。

- [ ] **Step 1: 失敗するテストを書く** — `test_render_choices`（上の形を、設計書 §8 の例の値で完全一致で assert）、`test_render_no_choices_goto`、`test_render_end`、`test_render_always_and_notes_deduplicated`、`test_render_without_notes_has_no_notes_section`、`test_render_reads_files_only_for_current_state`（他のステートの `prompt` ファイルを消しても `render_step` が成功する）、`test_render_missing_prompt_file_raises_flowerror`。
- [ ] **Step 2: 失敗を確認**
- [ ] **Step 3: 実装**
- [ ] **Step 4: 成功を確認**
- [ ] **Step 5: Commit** — `git commit -m "feat(flow): render step output"`

---

### Task 6: run の状態と遷移（start / next / status）

**Files:**
- Modify: `shared/flow/flow.py`
- Test: `tests/test_runs.py`

**Interfaces:**
- Consumes: `load_definition`, `render_step`（Task 4, 5）
- Produces:
  - `@dataclass class Run: run_id: str; definition: str; definition_hash: str; current: str; visits: dict[str, int]; history: list[dict]; status: str`（JSON のキーは `schema=1` とあわせて同名。`history` の要素は `{"state", "label", "at"}`、`status` は `"running"` / `"ended"`）
  - `def step_target(defn: Definition, visits: dict[str, int], current: str, label: str | None) -> str`（純粋関数。次に入るステート ID を返す。`max_visits` に達していれば `on_exceed` を返す。ラベル不正は `FlowError`）
  - `def start_run(defn_path: Path, state_dir: Path, cmd: str = "flow") -> str`（run を保存し、最初のステップの出力を返す。開始ステートの訪問回数は 1）
  - `def next_step(run_id: str, label: str | None, state_dir: Path, cmd: str = "flow", force: bool = False) -> str`
  - `def status_text(run_id: str, state_dir: Path) -> str`（現在地・訪問回数・履歴）

**挙動**
- run-id は `YYYYMMDD-HHMM-<3 文字の乱数>`。保存先は `state_dir / f"{run_id}.json"`（原子的に書く: 一時ファイルへ書いて `os.replace`）。
- run が見つからないときのメッセージは `run not found: <id> (looked in <state_dir>)`。
- エラー時は状態ファイルを**書き換えない**: 不明な run-id、`ended` の run、ラベル必須なのに未指定、分岐なしなのに `--result` あり、選べないラベル（メッセージに有効なラベルの一覧）、定義ファイルが消えている、ハッシュ不一致（`force` なしのとき）、`force` で続行したが現在のステートが定義に存在しない。
- `end` ステートに入ったら `status = "ended"`。

- [ ] **Step 1: 失敗するテストを書く**
  - `test_start_returns_first_step_and_saves_run`
  - `test_next_follows_label_and_records_history`
  - `test_max_visits`: `max_visits = 2` のステートを 2 回までは通り、3 回目の入場で `on_exceed` へ移る（`step_target` も単体で）
  - `test_goto_step_needs_no_result`
  - `test_label_given_to_goto_step_is_error`
  - `test_unknown_label_leaves_state_unchanged_and_lists_choices`（Review Focus 2: `XXX` を渡すと、`xxx` / `other` を示すエラーで、`.json` の内容が不変）
  - `test_next_on_ended_run_is_error` / `test_unknown_run_id_is_error`（Review Focus 3）
  - `test_definition_deleted_after_start_is_error` / `test_definition_changed_is_refused_without_force` / `test_force_continues_with_new_hash`（Review Focus 4）
  - `test_status_text_shows_current_visits_history`
  - `test_state_file_is_valid_json_with_schema_1`
- [ ] **Step 2: 失敗を確認**
- [ ] **Step 3: 実装** — ハッシュは定義ファイルのバイト列の SHA-256（16 進）。`start_run` と `next_step` は、遷移の判断をすべて `step_target` に任せる。
- [ ] **Step 4: 成功を確認**
- [ ] **Step 5: Commit** — `git commit -m "feat(flow): run state and transitions"`

---

### Task 7: CLI（start / next / status / lint）

**Files:**
- Modify: `shared/flow/flow.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `start_run`, `next_step`, `status_text`, `lint`（Task 3, 6）
- Produces: `def main(argv: list[str] | None = None) -> int`、`if __name__ == "__main__": raise SystemExit(main())`

**仕様**
- サブコマンド: `start <定義>`、`next <run-id> [--result LABEL] [--force]`、`status <run-id>`、`lint <定義>`。
- `--state-dir`（既定: 環境変数 `FLOW_STATE_DIR`、なければ `Path.cwd() / ".flow" / "runs"`）。
- 出力の `next` コマンド接頭辞 `cmd` は、環境変数 `FLOW_CMD`、なければ `uv run <この実行ファイルの絶対パス>`（`Path(sys.argv[0]).absolute()`。symlink は解決しない）。
- `lint` の出力は 1 行 1 件で `error[<code>] <where>: <message>` / `warning[<code>] ...`。エラーが 1 件でもあれば終了コード 1、警告のみなら 0。
- `FlowError` は stderr に `error: <message>` を出して終了コード 1。引数エラーは argparse 既定の 2。

- [ ] **Step 1: 失敗するテストを書く** — `main([...])` を `capsys` で呼ぶ: `test_start_prints_step_and_exit_0`、`test_next_roundtrip`（`start` の出力から run-id を正規表現で取り出して `next` へ）、`test_lint_exit_1_on_error_and_0_on_warning_only`、`test_error_goes_to_stderr_with_prefix`、`test_run_not_found_mentions_state_dir`（Review Focus 5: 別の `tmp_path` を `--state-dir` にした `next` で、探したディレクトリ名がメッセージに含まれる）、`test_cmd_prefix_from_env`（`FLOW_CMD=flow` で出力が `flow next ...`）。`test_subprocess_smoke`: `subprocess.run([sys.executable, str(flow_py), "lint", str(p)])` の終了コード。
- [ ] **Step 2: 失敗を確認**
- [ ] **Step 3: 実装** — `FlowError` の捕捉と終了コードの対応、`cmd` 接頭辞の決定を `main` に集める。run が見つからないメッセージは Task 6 の形式をそのまま使う。
- [ ] **Step 4: 成功を確認** — `task test` と `task lint`。
- [ ] **Step 5: Commit** — `git commit -m "feat(flow): add CLI commands"`

---

### Task 8: dry-run

**Files:**
- Modify: `shared/flow/flow.py`
- Test: `tests/test_dry_run.py`

**Interfaces:**
- Consumes: `step_target`, `render_step`, `load_definition`（Task 4〜6）
- Produces: `def dry_run(defn_path: Path, results: list[str] | None, cmd: str = "flow") -> str`、CLI サブコマンド `dry-run <定義> [--results a,b,c]`

**挙動**
- 状態ファイルを作らない。run-id の表示は `dry-run`。
- `results` なし: 全ステートを定義順に `render_step` し、`---` の行で区切って連結する。
- `results` あり: `start` から `step_target` でたどり、各ステップを出力して区切る。ラベルを使い切って未終了なら、末尾に `(results exhausted at <id>)`。ラベルが不正なら `FlowError`。`end` に着いたら、ラベルが余っていても `(results left over: ...)` を末尾に出す。

- [ ] **Step 1: 失敗するテストを書く** — `test_dry_run_all_states`、`test_dry_run_follows_results_to_end`、`test_dry_run_exhausted`、`test_dry_run_leftover_results`、`test_dry_run_invalid_label_raises`、`test_dry_run_writes_no_files`（`tmp_path` に `.flow` が作られない）、`test_cli_dry_run`。
- [ ] **Step 2: 失敗を確認**
- [ ] **Step 3: 実装**
- [ ] **Step 4: 成功を確認**
- [ ] **Step 5: Commit** — `git commit -m "feat(flow): add dry-run"`

---

### Task 9: rename

**Files:**
- Modify: `shared/flow/flow.py`
- Test: `tests/test_rename.py`

**Interfaces:**
- Consumes: `lint`（Task 3）
- Produces: `def rename_state(defn_path: Path, old: str, new: str) -> None`（失敗時はファイルを書き換えない）、CLI サブコマンド `rename <定義> <旧ID> <新ID>`

**挙動**: 次の箇所だけを、行単位のテキスト置換で書き換える（本文やコメントは触らない）: `start = "old"`、`goto = "old"`、`on_exceed = "old"`、テーブル見出し `[states.old]` と `[[states.old.choices]]`。`old` が存在しない、`new` が ID 形式に合わない、`new` が既存、の場合は `FlowError`。置換後に `lint` し、**置換前になかったエラー**が出たら、元の内容に戻して `FlowError`。

- [ ] **Step 1: 失敗するテストを書く** — `test_rename_updates_all_references`（見出し・`goto`・`start`・`on_exceed` がすべて変わり、`lint` がエラーなし）、`test_rename_leaves_prompt_text_untouched`（プロンプト本文中の同じ語は変わらない）、`test_rename_unknown_old`、`test_rename_bad_new_id`、`test_rename_existing_new`、`test_rename_rolls_back_when_lint_regresses`（置換後に新しい lint エラーが出る定義を用意し、ファイルが元のバイト列のまま）、`test_cli_rename`。
- [ ] **Step 2: 失敗を確認**
- [ ] **Step 3: 実装** — 置換は正規表現で、ID の前後を引用符または `.` / `]` で区切って部分一致を避ける（`s1` を改名しても `s10` は変えない）。
- [ ] **Step 4: 成功を確認**
- [ ] **Step 5: Commit** — `git commit -m "feat(flow): add rename"`

---

### Task 10: feature への同梱と移行例

**Files:**
- Create: `plugins/feature-a/scripts/flow.py`（`../../../shared/flow/flow.py` への symlink）、`plugins/feature-a/skills/review-loop/SKILL.md`、`plugins/feature-a/skills/review-loop/flow.toml`、`plugins/feature-a/skills/review-loop/prompts/fix.md`
- Modify: `.gitignore`（`.flow/` を追加。ファイルがなければ作成）
- Test: `tests/test_e2e.py`

**Interfaces:**
- Consumes: CLI 全体（Task 7）

**移行例の定義**（手順書の典型 — 分岐とループ上限 — を表す）: `run_tests`（`choices`: `pass` → `report`、`fail` → `fix`）、`fix`（`prompt = { file = "prompts/fix.md" }`、`goto = "run_tests"`、`max_visits = 2`、`on_exceed = "report_fail"`）、`report`（`end`）、`report_fail`（`end`）。`notes.always` に禁止事項を 1 つ。

**`SKILL.md`**: frontmatter は `name: review-loop`、`description`、`allowed-tools: Bash(uv run ${CLAUDE_PLUGIN_ROOT}/scripts/flow.py:*)`。本文は、`uv run ${CLAUDE_PLUGIN_ROOT}/scripts/flow.py start ${CLAUDE_PLUGIN_ROOT}/skills/review-loop/flow.toml` を実行し、出力の指示に従い、出力に書かれた `next` コマンドを実行し、`Flow complete.` と出るまで繰り返す、という数行だけ（`SKILL.md` の本文は英語で書く）。

- [ ] **Step 1: 失敗するテストを書く** — `tests/test_e2e.py::test_review_loop_end_to_end`: symlink 経由の `plugins/feature-a/scripts/flow.py` を `subprocess` で実行する（`cwd=tmp_path`、`FLOW_CMD` は未設定）。`flow lint` が終了コード 0 → `start` の出力から run-id と、コピー可能な `next` コマンド（`uv run .../flow.py next ...`）を取り出す → `fail` → `fail` → 3 回目の `fix` 入場で `report_fail` に着き、出力が `Flow complete.` で終わる。`tmp_path/.flow/runs/` に JSON が 1 つできている。`test_symlink_is_relative`: `os.readlink` の結果が相対パス。
- [ ] **Step 2: 失敗を確認**
- [ ] **Step 3: 作成** — `ln -s ../../../shared/flow/flow.py plugins/feature-a/scripts/flow.py`、`shared/flow/flow.py` に実行ビット、移行例の 3 ファイル、`.gitignore`。
- [ ] **Step 4: 成功を確認** — `task test`、`claude plugin validate .`。
- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat: bundle flow engine into feature-a with a sample flow"`

---

### Task 11: core プラグイン（作成・レビュー支援）

**Files:**
- Create: `plugins/core/.claude-plugin/plugin.json`、`plugins/core/scripts/flow.py`（symlink）、`plugins/core/skills/flow-author/SKILL.md`、`plugins/core/skills/flow-review/SKILL.md`
- Modify: `.claude-plugin/marketplace.json`（`core` を追加）、`README.md`（構成図に `core` と `flow` の使い方を、**英語で**追記）

**内容**
- `flow-author`: 既存の手順書型 skill（または、ユーザーが口頭で述べた手順）から `flow.toml` を作る手順。ラベルは ID（`s1_1` など）にして番号と分ける、長い本文は `{ file }` へ、分岐は `when` に判断基準を書く、書いたら必ず `flow lint` と `flow dry-run` を実行して指摘を直す、改名は `flow rename` を使う、というガイド。
- `flow-review`: 定義のレビュー（`flow lint` の結果の読み方、`flow dry-run --results` による経路確認）と、実行のデバッグ（`flow status <run-id>` の履歴を読んで、どこで想定とずれたかを説明する）の手順。
- どちらも `allowed-tools: Bash(uv run ${CLAUDE_PLUGIN_ROOT}/scripts/flow.py:*)` を持つ。

- [ ] **Step 1: 失敗する検証を用意** — `claude plugin validate .` が、`marketplace.json` に追加した `core` の `plugin.json` 不在で失敗することを確認する（先に `marketplace.json` を編集してから実行）。
- [ ] **Step 2: 失敗を確認** — 期待: validate が `core` について FAIL。
- [ ] **Step 3: 作成** — 上記ファイル一式。`flow.py` は Task 10 と同じ要領で相対 symlink。
- [ ] **Step 4: 成功を確認** — `claude plugin validate .` が通り、`task test` も全部通る。
- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat: add core plugin with flow-author and flow-review skills"`

---

## 計画の外（手動の確認）

次の 2 つは、GitHub のリポジトリができてから行う。完了したら `docs/BACKLOG.md` の B-005 を `done` にする。

1. B-005 の 3 点: `${CLAUDE_PLUGIN_ROOT}` がキャッシュのパスに展開される、キャッシュ内の symlink 実体で `review-loop` が動く、`allowed-tools` で承認が省略される。
2. 設計書 §11 の最後の基準: 実際の手順書型 skill を 1 つ、`flow-author` で定義へ移し、元の skill と同じ結果が得られることを確認する。
