# 開発用プラグイン（deskil-dev）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** バックログ運用（積む・優先順位・やり方の選択・実装して PR）を、flow エンジンで書いた 4 つのスキルとして `deskil-dev` プラグインで配布し、操作を機械化する `backlog.py` と新しい書式を導入する。

**Architecture:** `backlog.py` は標準ライブラリだけの単一ファイル。テキストを受け取って新しいテキストを返す純粋関数（`parse` / `lint` / `set_field` / `archive_item`）を中心にし、ファイル入出力と引数処理は `main` に閉じる。プラグインは `flow.py` と `backlog.py` を相対 symlink で同梱し、4 つのスキルは `review-loop` と同じ薄い `SKILL.md` ＋ `flow.toml`。

**Tech Stack:** Python 3.11+（標準ライブラリのみ）、`uv run`、pytest、ruff、go-task、`gh`。

**Spec:** `docs/superpowers/specs/2026-11-22-deskil-dev-design.md`

## Global Constraints

- コード・コメント・ログ・エラーメッセージ・`README.md` は英語。`docs/` 配下は日本語（`CLAUDE.md`）。スキルの手順文（`flow.toml`、`SKILL.md`、`prompts/`）は英語。
- `backlog.py` は Python 3.11+、標準ライブラリのみ。先頭に `flow.py` と同じ `# /// script` ヘッダー（`requires-python = ">=3.11"`、`dependencies = []`）と shebang を持ち、実行ビットを付ける。
- 同梱は相対 symlink のみ。リンクはリポジトリ内を指す（`plugins/deskil-dev/scripts/{flow.py,backlog.py}` → `../../../shared/...`）。
- 優先度は `P1` / `P2` / `P3`（既定 `P2`）。状態は `todo` / `ready` / `done` / `dropped`。
- バックログの値は 1 行。`set` は改行を含む値を拒否する。
- `backlog.py` は、利用者の文章を書き換えず、項目の並びも変えない。触るのは対象の行（と `archive` で移す項目ブロック）だけ。
- 終了コード: 成功 0、`lint` が問題を検出 1、使い方・入出力のエラー 2（メッセージは標準エラーへ、トレースバックなし）。
- `superpowers` を必須にしない。手順文は「あれば使う」と書く。
- コミットメッセージは `-m` を 2 つ使い、2 つ目に `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>` を付ける。Bash は 1 回に単純なコマンド 1 つ（`&&`・heredoc を使わない）。

## Review Focus

仕様が暗に求めるが、どのタスクの正常系テストにも出てこない入力。各行のテストを、持ち主のタスクに入れる。

1. 運用ルール内のコードブロックにある `### B-NNN タイトル`（書式の例）を、項目として数えない（Task 1）。
2. 対象ファイルがない・空のとき、トレースバックでなく分かるメッセージで終了コード 2 になる（Task 1）。
3. `set` の値に改行が入っていたら拒否し、ファイルを変えない。存在しない ID・キーも同様（Task 3）。
4. `（なし）` の置き場所表示がある空の `## done / dropped` へ `archive` しても、項目が正しい位置に入り、`（なし）` が消える（Task 3）。
5. 依存先が `dropped` または存在しないとき、`list` はブロック中と示し、`lint` は存在しない依存先を誤りとして報告する（Task 1・2）。

---

### Task 0: ブランチの準備

**Files:** なし（git のみ）

- [ ] **Step 1:** `git switch -c feature/deskil-dev`（未コミットの変更は引き継がれる）。
- [ ] **Step 2: 改名と README の修正だけをコミットする。** 対象は `plugins/`（deskil への改名）、`tests/test_deskil_plugin.py`、`.claude-plugin/marketplace.json`、`README.md`、`docs/BACKLOG.md`。`git add` で明示し、メッセージは `refactor: rename the core plugin to deskil and fix the install command`。
- [ ] **Step 3:** 設計書と本計画書（`docs/superpowers/`）を `docs: add the deskil-dev design and plan` でコミットする。
- [ ] **Step 4:** `git status` がきれいで、`task test` が通ることを確認する。

---

### Task 1: backlog.py の読み取り（parse / next-id / show / list）

**Files:**
- Create: `shared/backlog/backlog.py`（実行ビット付き）、`tests/test_backlog.py`
- Modify: `tests/conftest.py`（`shared/backlog` を `sys.path` に足し、`backlog` フィクスチャを返す）

**Interfaces:**
- Produces（以降のタスクが使う。すべて `shared/backlog/backlog.py`）:
  - 定数 `STATES = ("todo","ready","done","dropped")`、`PRIORITIES = ("P1","P2","P3")`、`SECTION_ACTIVE = "todo / ready"`、`SECTION_ARCHIVE = "done / dropped"`、`FIELD_ORDER = ("状態","優先度","依存","追加","背景","概要","判断","完了","PR")`
  - `class BacklogError(Exception)`
  - `@dataclass(frozen=True) class Problem: line: int; message: str`（`line` は 1 始まり。ファイル全体の問題は 0）
  - `@dataclass class Item: id: str; title: str; section: str; start: int; end: int; fields: list[tuple[str, str, int]]`（`start` は見出し行、`end` は項目の次の行、どちらも 0 始まりの行番号。`fields` は `(キー, 値, 行番号)`）と、メソッド `get(key) -> str | None`
  - `@dataclass class Backlog: lines: list[str]; items: list[Item]; problems: list[Problem]`
  - `parse(text: str) -> Backlog`、`next_id(bl: Backlog) -> str`、`blocked_by(bl: Backlog, item: Item) -> list[str]`、`sorted_items(bl: Backlog, statuses: set[str] | None) -> list[Item]`、`render_list(bl, statuses: set[str] | None) -> str`、`render_show(bl, id: str) -> str`、`main(argv: list[str] | None = None) -> int`

**書式の取り決め（テストで固定する）:**
- 項目は `## todo / ready` と `## done / dropped` の節の中にある `### B-NNN タイトル`（`NNN` は 3 桁以上の数字）。` ``` ` で囲まれたブロック内の行は無視する。節の外や、`B-NNN` の形でない `###` 見出しは、`Problem` として `bl.problems` に積む。
- 欄は項目内の `- キー: 値` の行（最初の `: ` で分割）。
- `list` の 1 行: `<ID>  <状態>  <優先度、なければ ->  <タイトル>`（区切りは空白 2 つ）。ブロック中なら末尾に `  [blocked by B-009, B-011]`。既定は `todo` / `ready` のみ、`--all` で全件、`--status a,b` で指定。並びは「状態（ready, todo, done, dropped）→ 優先度（P1, P2, P3, なし）→ ID」。
- ブロック中: 依存先のどれかが、存在しない・`done` でない。
- `show <ID>` は、その項目のブロック（見出しから末尾の空行を除く）をそのまま出す。
- `next-id`: 最大の ID + 1（3 桁ゼロ埋め）。項目がなければ `B-001`。
- 共通オプション `--file <path>`（既定 `docs/BACKLOG.md`）。

- [ ] **Step 1: 失敗するテストを書く（`tests/test_backlog.py`）。** 小さな `SAMPLE` 文字列を定数で持つ（運用ルール内に ` ``` ` で囲んだ `### B-NNN タイトル` の例、`todo` 2 件 + `ready` 1 件（うち 1 件は `依存: B-001`）、`## done / dropped` に `done` 1 件）。次のテストを書く:
  - `test_parse_ignores_headings_inside_code_fences`（項目数が 4、`B-NNN` が現れない）— Review Focus 1
  - `test_parse_reads_fields_and_line_ranges`（`get("優先度")`、`start` / `end`）
  - `test_parse_reports_malformed_headings`（`### B-1 x` が `problems` に 1 件）
  - `test_next_id`（`SAMPLE` で次の番号、空のバックログで `B-001`）
  - `test_list_order_and_default_filter`（ready が先、同じ状態では P1 < P2 < P3 < なし、done は既定で出ない）
  - `test_list_marks_blocked_items`（未完了の依存、`dropped` の依存、存在しない依存のそれぞれで `[blocked by ...]`）— Review Focus 5
  - `test_show_prints_one_item_block`
  - `test_cli_missing_file_exits_2`（`main(["--file", missing, "list"])` が 2 を返し、標準エラーにパスを含むメッセージ。トレースバックなし）、`test_cli_empty_file`（空ファイルは、項目なしとして `list` が空出力・終了コード 0）— Review Focus 2
- [ ] **Step 2:** `uv run --with pytest pytest tests/test_backlog.py -q` を実行し、`backlog` が import できず失敗することを確認する。
- [ ] **Step 3:** `conftest.py` に `shared/backlog` のパスと `backlog` フィクスチャを足す。`backlog.py` に上記のインターフェースを実装する。パーサは行を走査し、`## ` の見出しで節を切り替える。`main` は `argparse` のサブコマンド（`next-id` / `list` / `show`）と共通の `--file`。`BacklogError` は標準エラーに出して 2 を返す。`chmod +x`。
- [ ] **Step 4:** Step 2 のコマンドを再実行し、すべて通ることを確認する。
- [ ] **Step 5:** `tests/test_script_header.py` に `backlog.py` も `# /// script` ヘッダーを持つことを確認するテストを足し、実行ビットのテストも足す。`task test` と `task lint` が通る。
- [ ] **Step 6: Commit** `feat(backlog): parse the backlog and add next-id, show and list`

---

### Task 2: backlog.py の lint

**Files:**
- Modify: `shared/backlog/backlog.py`、`tests/test_backlog.py`

**Interfaces:**
- Consumes: Task 1 の `Backlog` / `Item` / `Problem` / `blocked_by`
- Produces: `lint(bl: Backlog) -> list[Problem]`。CLI `lint` は、問題を `<path>:<line>: <message>` の形で 1 行ずつ標準出力に出し、1 件以上なら終了コード 1、0 件なら何も出さず 0。

**検査項目（問題 1 件 = 1 行。メッセージは英語）:**
- `bl.problems`（見出しの書式）をそのまま含める。
- ID の重複。同じ項目内の欄キーの重複。
- 必須欄の欠落: すべての項目で `状態`・`追加`・`背景`・`概要`。`todo` / `ready` では `優先度` も。
- 値の形式: 状態は 4 種、優先度は P1〜P3、`追加` / `完了` は `YYYY-MM-DD`、`依存` は `B-NNN` のカンマ区切り、`PR` は `#数字`。
- 内容の整合: `ready` / `dropped` に `判断`、`done` に `完了` と `PR`、`dropped` に `PR` がない。
- 置き場: `todo` / `ready` は `SECTION_ACTIVE`、`done` / `dropped` は `SECTION_ARCHIVE` にある。
- 依存先が実在する。依存が循環していない。

- [ ] **Step 1: 失敗するテストを書く。** `test_lint_clean_sample`（`SAMPLE` で 0 件）と、`SAMPLE` の一部を書き換えて 1 件の問題を作るパラメータ化テスト `test_lint_detects`（上の検査項目ごとに 1 ケース。問題の行番号とメッセージの一部を検証）。`test_lint_dependency_cycle`（B-A ⇄ B-B）、`test_lint_unknown_dependency`（Review Focus 5）、`test_cli_lint_exit_codes_and_format`（終了コード 1 と出力形式、きれいなら 0 で出力なし）。
- [ ] **Step 2:** `uv run --with pytest pytest tests/test_backlog.py -q -k lint` で失敗を確認する。
- [ ] **Step 3:** `lint` と CLI のサブコマンドを実装する。循環検出は、依存を辺とした深さ優先探索。
- [ ] **Step 4:** テストを再実行して通ることを確認し、`task test` / `task lint` を通す。
- [ ] **Step 5: Commit** `feat(backlog): add the lint subcommand`

---

### Task 3: backlog.py の書き込み（set / archive）

**Files:**
- Modify: `shared/backlog/backlog.py`、`tests/test_backlog.py`

**Interfaces:**
- Consumes: Task 1 の `parse` / `Item` / `FIELD_ORDER`、Task 2 の `lint`
- Produces:
  - `set_field(text: str, id: str, key: str, value: str) -> str`
  - `archive_item(text: str, id: str, outcome: str, pr: int | None, today: date) -> str`（`outcome` は `"done"` または `"dropped"`）
  - CLI: `set <ID> <キー> <値>`、`archive <ID> --done --pr N`、`archive <ID> --dropped`。CLI は変更後のテキストを `parse` と `lint` に通してから書き込む（問題があればファイルを変えず、終了コード 2）。`archive` の日付は `date.today()`。

**取り決め:**
- `set` が扱うキーは `状態`・`優先度`・`依存`・`完了`・`PR`。ほかは拒否する。値に改行があれば拒否する。`状態` は `todo` / `ready` だけを許し、`done` / `dropped` は `archive` を案内するメッセージで拒否する。置き場が `SECTION_ARCHIVE` の項目の `状態` は変えられない。
- 欄がなければ、`FIELD_ORDER` で自分より前にある欄のうち最後のものの直後の行へ足す（前の欄が 1 つもなければ見出しの直後）。欄があれば、その行だけを書き換える。それ以外の行は 1 文字も変えない。
- `archive`: 項目ブロックを元の節から取り除き（直後の空行 1 つを含む）、`## done / dropped` 節の末尾へ移す。節に `（なし）` の行があれば、その行（と直後の空行）を取り除く。`done` は `状態: done` にして、ブロックの最後に `完了: <今日>` と `PR: #N` を足す（`--pr` が必須）。`dropped` は `状態: dropped`。`判断` がない項目は拒否する。`PR` を `dropped` に付けない。

- [ ] **Step 1: 失敗するテストを書く。**
  - `set`: `test_set_replaces_only_that_line`（差分が 1 行だけ）、`test_set_inserts_missing_field_in_order`（`優先度` と `依存` を足したとき `FIELD_ORDER` どおりの位置）、`test_set_rejects_newline_value_and_unknown_id_and_key`（ファイルを書き換えない）— Review Focus 3、`test_set_state_done_is_refused_with_hint`。
  - `archive`: `test_archive_done_moves_block_and_adds_completion_fields`、`test_archive_dropped_requires_judgement`、`test_archive_into_empty_section_removes_placeholder`（`（なし）` が消え、位置が正しい。移動後に `lint` が 0 件）— Review Focus 4、`test_archive_done_requires_pr`、`test_archive_leaves_other_text_untouched`。
  - CLI: `test_cli_set_writes_file`、`test_cli_set_does_not_write_when_lint_would_fail`。
- [ ] **Step 2:** テストを実行し、失敗を確認する。
- [ ] **Step 3:** `set_field` / `archive_item` と CLI を実装する。行の入れ替えは `Backlog.lines` に対して行い、`"\n".join` で戻す。
- [ ] **Step 4:** テストが通ること、`task test` / `task lint` が通ることを確認する。
- [ ] **Step 5: Commit** `feat(backlog): add the set and archive subcommands`

---

### Task 4: バックログの書式の移行

**Files:**
- Modify: `docs/BACKLOG.md`、`tests/test_backlog.py`
- Create: 使い捨ての移行スクリプト（スクラッチパッドに置き、コミットしない）

**Interfaces:** Consumes: Task 3 の `set_field`、Task 2 の `lint`

- [ ] **Step 1: 失敗するテストを書く。** `test_real_backlog_is_clean`（実際の `docs/BACKLOG.md` を `lint` して 0 件）、`test_real_backlog_has_priorities_and_known_dependencies`（`todo` / `ready` の全項目が `P1`〜`P3` を持つ。B-010 の依存が B-009、B-012 の依存が B-011、B-014 の依存が B-011 と B-012）。
- [ ] **Step 2:** 失敗を確認する（優先度の欄がまだない）。
- [ ] **Step 3: 移行する。** スクラッチパッドに Python スクリプトを `Write` で作り、`set_field` を使って、`todo` / `ready` の全項目に `優先度: P2` を、B-010 / B-012 / B-014 に上記の `依存` を足す。`python3 -I <script>` で実行する。
- [ ] **Step 4:** `docs/BACKLOG.md` の冒頭（運用ルールと書式）を更新する（日本語）。新しい欄（`優先度`・`依存`・`完了`・`PR`）の意味と、「ブロック中」「並べ替えは `backlog.py list` が行う」を書く。書式の例のコードブロックも設計書の形に合わせる。B-022「完了項目の別ファイルへの分離」を `todo` / `P3` で追記する（背景: 項目が増えるとファイルが長くなり、読むトークンが増える。初版は 1 ファイルで始めた）。
- [ ] **Step 5:** Step 1 のテストを含め `task test` が通ることを確認し、`uv run shared/backlog/backlog.py list` の出力を目で見て、並びと依存の印が妥当か確かめる。
- [ ] **Step 6: Commit** `docs: add priority, dependency and completion fields to the backlog`

---

### Task 5: deskil-dev プラグインの骨組み

**Files:**
- Create: `plugins/deskil-dev/.claude-plugin/plugin.json`、`plugins/deskil-dev/scripts/flow.py`（symlink → `../../../shared/flow/flow.py`）、`plugins/deskil-dev/scripts/backlog.py`（symlink → `../../../shared/backlog/backlog.py`）、`tests/test_deskil_dev_plugin.py`
- Modify: `.claude-plugin/marketplace.json`

**Interfaces:** Produces: テストモジュールの定数 `DEV`（`plugins/deskil-dev`）と `SKILLS = ["backlog-add", "backlog-prioritize", "backlog-decide", "backlog-implement"]`（以降のタスクのテストが使う。この時点では、スキルのテストは `pytest.mark.skipif` ではなく、スキルのディレクトリがあるものだけを対象にするパラメータ化にして、Task 6・7 で自然に増えるようにする）。

- [ ] **Step 1: 失敗するテストを書く。** `test_marketplace_lists_deskil_dev`（`source == "./plugins/deskil-dev"`）、`test_plugin_json_names_deskil_dev`（名前、`version`）、`test_scripts_are_relative_symlinks_into_shared`（`flow.py` と `backlog.py` の両方。相対、解決先が `shared/` 配下の期待のファイル）。
- [ ] **Step 2:** 失敗を確認する。
- [ ] **Step 3:** `plugin.json`（`version` は `0.1.0`、説明は英語）、2 つの symlink（`ln -s` を 1 回ずつ）、`marketplace.json` のエントリを足す。
- [ ] **Step 4:** テストが通ることを確認する。さらに `claude plugin validate .` が使えれば実行し、結果を確かめる（使えなければ、その旨を報告に書く）。
- [ ] **Step 5: Commit** `feat: add the deskil-dev plugin skeleton`

---

### Task 6: backlog-add と backlog-prioritize

**Files:**
- Create: `plugins/deskil-dev/skills/backlog-add/{SKILL.md,flow.toml}`、`plugins/deskil-dev/skills/backlog-prioritize/{SKILL.md,flow.toml}`（長い文面は `prompts/*.md` に分けてよい）
- Modify: `tests/test_deskil_dev_plugin.py`

**Interfaces:** Consumes: Task 5 の `DEV` / `SKILLS`。`SKILL.md` の形は `plugins/feature-a/skills/review-loop/SKILL.md` と同じ（`flow.py start <この flow.toml>` を実行し、出力に従い、`Flow complete.` まで繰り返す）。`allowed-tools` は `Bash(uv run ${CLAUDE_PLUGIN_ROOT}/scripts/flow.py:*), Bash(uv run ${CLAUDE_PLUGIN_ROOT}/scripts/backlog.py:*)`。

**backlog-add の flow（状態名・選択肢・遷移は固定）:**
- `check_dup`: 既存の項目を `backlog.py list --all` で見て、重複を判断する。選択肢 `new` → `write`、`duplicate` → `update_existing`。
- `update_existing`: `show` で既存項目を読み、`Edit` で追記する。→ `lint`。
- `write`: `next-id` で採番し、`docs/BACKLOG.md` の `todo / ready` 節の末尾に、`todo` / `P2` で追記する（書式は `docs/BACKLOG.md` の冒頭に従う。`背景` に「なぜ見送るか」を書く）。→ `lint`。
- `lint`: `backlog.py lint` を実行。選択肢 `ok` → `report`、`errors` → `fix`。
- `fix`: lint の指摘を直す。→ `lint`。`max_visits = 2`、`on_exceed = "report_fail"`。
- `report`（終了）、`report_fail`（終了。直せなかった指摘を報告する）。

**backlog-prioritize の flow:**
- `survey`: `backlog.py list` で `todo` / `ready` を見て、必要な項目だけ `show` で読む。→ `propose`。
- `propose`: 項目ごとに P1〜P3 の案と理由を作る（基準: 依存の先にある項目と、他を詰まらせる項目を上げる。効果が小さく手間の大きい項目を下げる）。→ `confirm`。
- `confirm`: 案をユーザーに見せ、承認または修正を待つ（待たずに進めない）。選択肢 `approved` → `apply`、`revise` → `propose`。`propose` は `max_visits = 3`、`on_exceed = "report_unchanged"`。
- `apply`: 変更が必要な項目だけ `backlog.py set <ID> 優先度 <P>` を実行する。→ `lint`。
- `lint`: `backlog.py lint`。選択肢 `ok` → `report`、`errors` → `fix_prio`（原因を直して `lint` へ戻る。`max_visits = 2`、`on_exceed = "report_unchanged"`）。
- `report`（終了）、`report_unchanged`（終了。変更しなかったことを報告する）。

- [ ] **Step 1: 失敗するテストを書く（`SKILLS` のうち存在するものをパラメータ化）。**
  - `test_skill_frontmatter`（`name` がディレクトリ名と一致、`description` あり、`allowed-tools` が上記の文字列）
  - `test_skill_runs_the_flow`（`SKILL.md` に `flow.py start` と `flow.toml` のパス、`Flow complete.` がある）
  - `test_flow_lints_clean`（`DEV/scripts/flow.py lint <flow.toml>` を `subprocess` で実行。終了コード 0・出力なし）
  - `test_add_lint_failures_end_in_report_fail`（`dry-run <backlog-add の flow.toml> --results new,errors,errors,errors` の出力に `[report_fail] (run: dry-run)` があり、`Flow complete.` で終わる）
  - `test_prioritize_revision_limit`（`--results` に `revise` を上限を超える回数だけ並べると `[report_unchanged]` に着く）
- [ ] **Step 2:** 失敗を確認する。
- [ ] **Step 3:** 2 つのスキルを `flow-author` の書き方（`plugins/deskil/skills/flow-author/SKILL.md`）に従って作る。作ったら `flow.py lint` と `dry-run`（通常経路と上限に達する経路）で確かめる。
- [ ] **Step 4:** テストが通ること、`task test` / `task lint` が通ることを確認する。
- [ ] **Step 5: Commit** `feat(deskil-dev): add backlog-add and backlog-prioritize`

---

### Task 7: backlog-decide と backlog-implement

**Files:**
- Create: `plugins/deskil-dev/skills/backlog-decide/{SKILL.md,flow.toml}`、`plugins/deskil-dev/skills/backlog-implement/{SKILL.md,flow.toml}`（`prompts/*.md` 可）
- Modify: `tests/test_deskil_dev_plugin.py`

**Interfaces:** Consumes: Task 6 と同じ `SKILL.md` の形と `allowed-tools`。`backlog-implement` の `SKILL.md` は、`allowed-tools` に `git` / `gh` を足さない（手順の中で承認を受ける）。

**backlog-decide の flow:**
- `pick`: ユーザーが指定した項目、なければ `list` の先頭のうちブロック中でない `todo`。→ `investigate`。見つからなければ `report_none`（終了）。選択肢 `found` → `investigate`、`none` → `report_none`。
- `investigate`: `show <ID>` と、関連するコード・文書を読む。→ `options`。
- `options`: 案を 2〜3 個、トレードオフと推奨を付けて示す（`brainstorming` スキルがあれば使う）。→ `confirm`。
- `confirm`: ユーザーの選択を待つ。選択肢 `ready` → `write_decision`、`dropped` → `drop`、`defer` → `note_open`。
- `write_decision`: 決めた内容を `判断` に書き（`Edit`）、`set <ID> 状態 ready` を実行する。→ `lint`。
- `drop`: 理由を `判断` に書き、`archive <ID> --dropped` を実行する。→ `lint`。
- `note_open`: 分かったことを `概要` の未決に追記する。状態は変えない。→ `lint`。
- `lint`: 選択肢 `ok` → `report`、`errors` → `fix`（原因を直して `lint` へ。`max_visits = 2`、`on_exceed = "report_fail"`）。
- `report`、`report_none`、`report_fail`（すべて終了）。

**backlog-implement の flow:**
- `pick`: ユーザーが指定した項目、なければ `list` で、ブロック中でない `ready` の優先度最上位。選択肢 `found` → `prepare`、`none` → `report_none`。
- `prepare`: 作業ツリーがきれいか確認し（汚れていたら止めて報告）、ブランチ `backlog/<ID>-<slug>`（`<slug>` は題名を英小文字とハイフンにしたもの）を作る。worktree が使えれば使う。→ `plan`。
- `plan`: `判断` に書かれたやり方を実装の計画にする。小さい変更はその場で短く、大きければ `docs/superpowers/plans/` に書く（`writing-plans` があれば使う）。→ `implement`。
- `implement`: テストを先に書いて実装する（`test-driven-development` があれば使う）。リポジトリの `CLAUDE.md` の規約（言語、コメント）に従う。→ `verify`。
- `verify`: そのリポジトリのテストと lint を実行する（Taskfile に `test` / `lint` があれば `task test` / `task lint`）。選択肢 `pass` → `commit`、`fail` → `fix`。
- `fix`: 失敗を直す。→ `verify`。`max_visits = 2`、`on_exceed = "report_fail"`。
- `commit`: 変更をコミットする（`CLAUDE.md` のコミット規約に従う）。→ `open_pr`。
- `open_pr`: ブランチを push し、`gh pr create` で PR を作る。マージはしない。ユーザーに PR の URL を知らせる。→ `finish_backlog`。
- `finish_backlog`: PR 番号を使って `backlog.py archive <ID> --done --pr <N>` を実行し、`lint` を通し、別コミットにして push する。→ `report`。
- `report`（終了。PR の URL を報告）、`report_none`（終了）、`report_fail`（終了。PR は作らない。失敗の内容と、ブランチの状態を報告する）。

- [ ] **Step 1: 失敗するテストを書く。** Task 6 のパラメータ化テストは `SKILLS` が揃うので自動で 4 つ目まで対象になる。加えて:
  - `test_decide_paths`（`--results found,ready,ok` で `[write_decision]` を経て `Flow complete.`、`found,dropped,ok` で `[drop]`、`found,defer,ok` で `[note_open]`、`none` で `[report_none]`）
  - `test_implement_failure_limit_skips_pr`（`found,fail,fail,fail` の出力に `[report_fail] (run: dry-run)` があり、`[open_pr]` がない）
  - `test_implement_happy_path_order`（`found,pass` の出力で `prepare → plan → implement → verify → commit → open_pr → finish_backlog → report` の順に現れる）
- [ ] **Step 2:** 失敗を確認する。
- [ ] **Step 3:** 2 つのスキルを作り、`lint` と `dry-run` で確かめる。
- [ ] **Step 4:** テストが通ること、`task test` / `task lint` が通ることを確認する。
- [ ] **Step 5: Commit** `feat(deskil-dev): add backlog-decide and backlog-implement`

---

### Task 8: README・最終確認・PR・バックログの更新

**Files:**
- Modify: `README.md`（英語）、`docs/BACKLOG.md`

- [ ] **Step 1:** `README.md` の Plugins の表に `deskil-dev` を足し（4 つのスキルを書く）、Layout に `shared/backlog/` を足す。`backlog.py` の使い方（`list` / `show` / `next-id` / `set` / `archive` / `lint`）を短い節にまとめる。インストールの例に `deskil-dev@deskil` を足す。
- [ ] **Step 2:** `task test` と `task lint` を実行し、全件が通ることを確認する。`uv run shared/backlog/backlog.py lint` が 0 件であることも確認する。
- [ ] **Step 3:** 実際に `backlog.py` を使って確かめる（`list`、`show B-009`、`next-id`）。結果を見て、設計書の受け入れ条件を 1 つずつ確認する。
- [ ] **Step 4: Commit** `docs: describe the deskil-dev plugin and backlog.py in the README`
- [ ] **Step 5:** ブランチを push し、`gh pr create` で PR を作る（本文は日本語の概要＋テスト結果、末尾に `🤖 Generated with [Claude Code](https://claude.com/claude-code)`）。PR 番号を控える。
- [ ] **Step 6:** `backlog.py archive B-009 --done --pr <N>` と `backlog.py archive B-010 --done --pr <N>` を 1 回ずつ実行し、`lint` が 0 件であること、`task test` が通ることを確認する。
- [ ] **Step 7: Commit** `docs: mark B-009 and B-010 as done` → push。PR の URL を報告する。

---

## Self-Review

- **仕様の対応:** ゴール 1 → Task 5、ゴール 2 → Task 6・7、ゴール 3 → Task 1〜3、ゴール 4 → Task 4、ゴール 5 → Task 8。受け入れ条件の各項目に、対応するテストまたは確認がある。
- **設計書からの調整（1 件）:** 設計書の `implement` の骨組みは `finish_backlog → commit → open_pr → record_pr` だった。`archive --done` は `PR` を必須にし（`lint` も `done` に `PR` を要求する）、PR 番号は PR を作るまで分からないため、`open_pr` の後に `finish_backlog`（`archive --done --pr N` ＋別コミット）を置いて `record_pr` と統合した。「PR 番号は PR 作成後の別コミットで入れる」という設計書の方針は変わらない。
- **型の整合:** `Item` / `Backlog` / `Problem` の定義は Task 1 に集約し、Task 2・3 は同じ名前を使う。`set_field` / `archive_item` のシグネチャは Task 3 で定義し、Task 4 の移行スクリプトが使う。
