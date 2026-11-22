# deskil-dev で flow のコマンド実行を使う 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** flow の `run` の argv で `${DEF_DIR}` を使えるようにし、deskil-dev の固定引数の `backlog.py` コマンドを `run` に移す。

**Architecture:** `flow.py` が実行の直前に、確認済み ref の argv の `${DEF_DIR}` を定義ファイルのディレクトリ（絶対パス）へ置き換える。比較は展開前の文字列で行い、記録と表示には展開後の argv を載せる。deskil-dev の 3 つの `flow.toml` に `run` を足す。

**Tech Stack:** Python 3（標準ライブラリのみ）、pytest、`task`（`task test` / `task lint`）。

**Spec:** `docs/superpowers/specs/2026-11-22-deskil-dev-use-run-design.md`

## Global Constraints

- 編集するのは `shared/flow/flow.py`（実体）。`plugins/*/scripts/` のリンクは編集しない。
- ソースコードのコメント・ログ・エラーメッセージ・`README.md` は英語。`docs/` 配下は日本語。
- `cwd` には `${DEF_DIR}` を展開しない。`cwd` の制限（相対・`..` 禁止）は変えない。
- 展開するのは `${DEF_DIR}` だけ。他の `${...}` はそのまま渡し、`flow lint` は警告にする。
- 展開は、確認済み ref から取り出した argv に対して行う（TOCTOU 対策を維持）。ref との比較は展開前の文字列で行う。
- プロンプトからコマンドの文言は消さない。
- 実行しないステート: `pick`、`verify`、`prepare`（設計書の非ゴール）。
- `uv run --with pytest pytest tests -q` と `uv run --with ruff ruff check .` が通ること。

## Review Focus

- 定義ディレクトリの絶対パスに空白が含まれる: 展開後も 1 つの引数のまま渡る（シェルを通さないため）。
- 1 つの要素に `${DEF_DIR}` が複数、または文字列の途中にある（`x${DEF_DIR}/y`）: すべて置き換わる。
- ref 上の argv と作業ファイルの argv が展開前の文字列で一致しても、定義の場所が違えば展開結果は違う: 実行は常に実際の定義の場所で展開する。
- 実行されなかった場合（ref が引けない、定義が違う）の表示: 展開後の argv を出し、LLM がそのまま実行できる。
- `${DEF_DIR}` の綴りの誤り（`${DEFDIR}`、`$DEF_DIR`）: lint が警告し、実行時は展開されない。

---

### Task 1: flow の `${DEF_DIR}` 展開と lint

**Files:**
- Modify: `shared/flow/flow.py`（`_check_run`、`execute_state`、`render_command` まわり）
- Test: `tests/test_exec.py`（lint の節と実行の節に追記）

**Interfaces:**
- Produces: `expand_argv(argv: list[str], base_dir: Path) -> list[str]`（`${DEF_DIR}` を `str(base_dir)` に置き換える。他は変えない）。定数 `DEF_DIR_VAR = "${DEF_DIR}"`。
- Produces: lint の警告コード `unknown-variable`（`where` は `states.<id>.run`）。
- Consumes: 既存の `Issue(level, code, where, message)`、`Definition.base_dir`（絶対パス）、`execute_state` の `rec["argv"]`。

- [ ] **Step 1: 失敗するテストを書く（`tests/test_exec.py`）**
  - lint の節: `test_lint_warns_on_unknown_variable`。`run = ["echo", "${DEFDIR}/x"]` と `["echo", "$DEF_DIR"]` の定義は、`level == "warning"` かつ `code == "unknown-variable"` の Issue を 1 つ出し、error は出さない。`["echo", "${DEF_DIR}/x"]` は warning も error も出さない。
  - 実行の節: `test_def_dir_is_expanded_before_running`。`repo` に `commit(repo, _def(py("import sys; print(sys.argv[1])") [:-1] + ', "${DEF_DIR}/x"]'))` のように、argv の末尾に `"${DEF_DIR}/x"` を足した定義をコミットして `start_run` し、出力に `str(repo / "x")` が含まれ、`${DEF_DIR}` は含まれない。（`py()` は JSON 配列を返すので、末尾の `]` の前に要素を足す。読みにくければ、テスト内で `json.dumps([sys.executable, "-c", code, "${DEF_DIR}/x"])` を直接書く。）
  - `test_def_dir_with_space_stays_one_argument`: 空白を含むディレクトリ（`tmp_path / "a b"`）に作った git リポジトリ（`repo` と同じ手順）で、argv の個数を表示するコマンドを実行し、`${DEF_DIR}` を含む要素が 1 つの引数として届く。
  - `test_multiple_def_dir_in_one_element`: 1 要素に `${DEF_DIR}` が 2 回あるとき、2 回とも置き換わる。
  - `test_unexpanded_variable_other_than_def_dir_is_passed_through`: `${HOME}` は置き換わらず、そのまま子プロセスの argv に届く。
  - `test_not_executed_shows_expanded_argv`: 作業ファイルを ref と違う内容に書き換えた場合（`test_definition_modified_in_worktree_is_display_only` と同じ手順）、"not executed" の表示に展開後のパスが出て、`${DEF_DIR}` は出ない。
  - `test_command_differing_from_ref_is_decided_before_expansion`: ref 上は `["x", "${DEF_DIR}/a"]`、作業ファイルは `["x", "${DEF_DIR}/b"]` のとき、実行されない（`the command differs from ref`）。
  - `test_run_record_holds_expanded_argv`: 実行後の run の記録（`commands[0]["argv"]`）が展開後。

- [ ] **Step 2: テストが失敗することを確認する**

  Run: `uv run --with pytest pytest tests/test_exec.py -q`
  Expected: 追加した各テストが FAIL（`${DEF_DIR}` が展開されない、警告が出ない）。

- [ ] **Step 3: `shared/flow/flow.py` に実装する**
  - `expand_argv(argv: list[str], base_dir: Path) -> list[str]`: 各要素の `${DEF_DIR}` を `str(base_dir)` に `str.replace` で置き換える。
  - `_check_run`: `run` が正しい形のとき、各要素から `re.findall(r"\$\{[^}]*\}", a)` で見つけた `${...}` のうち `${DEF_DIR}` 以外について、`Issue("warning", "unknown-variable", f"{where}.run", ...)` を足す（メッセージは英語。`flow` が展開するのは `${DEF_DIR}` だけであることを書く）。`cwd` は検査しない。
  - `execute_state`: `rec["argv"]` を `expand_argv(list(st.run), defn.base_dir)` にする（表示と記録は展開後）。ref との比較（`entry.get("run") == list(st.run)`）は今のまま展開前で行う。実行する argv は `expand_argv(list(entry["run"]), defn.base_dir)`。
  - `render_command` は `result["argv"]`（展開後）をそのまま使うので変更不要。

- [ ] **Step 4: テストが通ることを確認する**

  Run: `uv run --with pytest pytest tests -q`
  Expected: すべて PASS（既存のテストを含む）。

- [ ] **Step 5: lint とコミット**

  Run: `uv run --with ruff ruff check .`
  Expected: エラーなし。

  ```bash
  git add shared/flow/flow.py tests/test_exec.py
  git commit -m "flow: expand ${DEF_DIR} in run argv (B-NNN)"
  ```

---

### Task 2: deskil-dev の flow に `run` を足す

**Files:**
- Modify: `plugins/deskil-dev/skills/add/flow.toml`、`plugins/deskil-dev/skills/decide/flow.toml`、`plugins/deskil-dev/skills/prio/flow.toml`
- Test: `tests/test_deskil_dev_plugin.py`

**Interfaces:**
- Consumes: Task 1 の `${DEF_DIR}` 展開。`backlog.py` は `${DEF_DIR}/../../scripts/backlog.py`（`skills/<name>/flow.toml` から 2 つ上の `scripts/`）。
- 書式: `run = ["uv", "run", "${DEF_DIR}/../../scripts/backlog.py", "<args>"]`。

- [ ] **Step 1: 失敗するテストを書く（`tests/test_deskil_dev_plugin.py`）**
  - `test_fixed_commands_are_run_by_the_flow`（パラメータ化）: 次の対応で、`flow.toml` を `tomllib` で読んだ `states[<state>]["run"]` が `["uv", "run", "${DEF_DIR}/../../scripts/backlog.py", *args]` に等しい。
    - add: `lint` → `["lint"]`、`write` → `["next-id"]`
    - decide: `lint` → `["lint"]`
    - prio: `lint` → `["lint"]`、`survey` → `["list"]`
  - `test_commands_not_in_scope_are_not_run`: decide と impl の `pick`、impl の `prepare` と `verify` に `run` がない。
  - `test_run_target_exists`: 各 `run` の argv[2] の `${DEF_DIR}` を、その `flow.toml` のディレクトリで置き換えて解決したパスが、実在するファイルである（リンク先も含む）。
  - `test_run_commands_work_in_a_project`: `tmp_path` に最小の `docs/BACKLOG.md`（既存のテストが使うフィクスチャか、`backlog.py` の lint が通る最小の本文）を置き、`expand_argv` で展開した add の `lint` の argv を `cwd=tmp_path` で実行して終了コード 0。`next-id` も終了コード 0 で、`B-` で始まる出力。
  - 既存の `dry_run` を使うテストが、`run` を足しても通る（`dry-run` はコマンドを実行しない）。

- [ ] **Step 2: テストが失敗することを確認する**

  Run: `uv run --with pytest pytest tests/test_deskil_dev_plugin.py -q`
  Expected: 追加したテストが FAIL。

- [ ] **Step 3: 3 つの `flow.toml` を編集する**
  - 設計書の表のとおりに `run` を足す（add の `lint` と `write`、decide の `lint`、prio の `lint` と `survey`）。
  - 各 `prompt` のコマンドの文言は残す。`lint` ステートは、「実行結果の終了コード 0 で出力なしが ok」と分かる文面にし、`when` を「the command above exited 0 and printed nothing」「the command above printed problems or exited non-zero」の趣旨に直す。コマンドが実行されなかった旨の表示が出た場合は、同じコマンドを自分で実行するよう、プロンプトに 1 行足す（3 flow で同じ文言にする）。
  - `write`（add）は、`next-id` の結果をそのまま ID に使うよう書き、「`backlog.py next-id` を実行する」の文言は「結果が表示されない場合に実行する」趣旨に直す。

- [ ] **Step 4: テストが通ることを確認する**

  Run: `uv run --with pytest pytest tests -q`
  Expected: すべて PASS。

  Run: `uv run plugins/deskil-dev/scripts/flow.py lint plugins/deskil-dev/skills/add/flow.toml`（decide、prio も同様）
  Expected: エラーも警告もない。

- [ ] **Step 5: 実機で 1 回確認する**

  `plugins/deskil-dev/skills/prio/flow.toml` を `main` にコミットした状態で、`uv run plugins/deskil-dev/scripts/flow.py start plugins/deskil-dev/skills/prio/flow.toml` を実行する。
  Expected: `survey` に "Exit code: 0" と `backlog.py list` の出力が出る。確認後、起動した run は `flow` の通常の手順で終わらせるか、状態ディレクトリの run を残してよい。

- [ ] **Step 6: コミット**

  ```bash
  git add plugins/deskil-dev/skills tests/test_deskil_dev_plugin.py
  git commit -m "deskil-dev: run fixed backlog.py commands from the flows (B-NNN)"
  ```

---

### Task 3: ドキュメントとバックログ

**Files:**
- Modify: `plugins/deskil/skills/flow-author/SKILL.md`（`run` の説明、54 行目付近）、`README.md`（`start --ref` の記述の近く）、`docs/BACKLOG.md`

**Interfaces:**
- Consumes: Task 1 の `${DEF_DIR}`。

- [ ] **Step 1: `flow-author/SKILL.md` に追記する**
  - `run` の説明に、`${DEF_DIR}`（argv の中で、定義ファイルのあるディレクトリの絶対パスに置き換わる。`cwd` では使えない。他の `${...}` は展開されない）と、使いどころ（スクリプトをプラグインの中から指す: `["uv", "run", "${DEF_DIR}/../../scripts/x.py"]`）を英語で足す。

- [ ] **Step 2: `README.md` に追記する**
  - `run` / `--ref` を説明している箇所に、`${DEF_DIR}` の 1〜2 行（英語）を足す。該当箇所がなければ `flow.py` の説明のそばに足す。

- [ ] **Step 3: バックログを更新する**
  - `deskil-dev:add` のフローで、次の項目を `todo` として追加する（日本語）。番号は `backlog.py next-id` で取る。
    1. 「インストール済みプラグインで `--ref` の確認が通るか」の検証（通らない場合は、`flow` が定義の ref をどう決めるかを見直す）。
  - この計画の実装自体の項目は、`deskil-dev:add` → `decide` → `impl` のフローで扱う（この計画書を `impl` の入力にする）。コミットメッセージの `B-NNN` は、そのとき決まった ID に置き換える。

- [ ] **Step 4: 検証とコミット**

  Run: `uv run --with pytest pytest tests -q` と `uv run --with ruff ruff check .` と `uv run plugins/deskil-dev/scripts/backlog.py lint`
  Expected: すべて成功（lint は出力なし）。

  ```bash
  git add plugins/deskil/skills/flow-author/SKILL.md README.md docs/BACKLOG.md
  git commit -m "docs: describe ${DEF_DIR} for flow run commands (B-NNN)"
  ```

---

## 自己レビュー

- 設計書の対応: flow の変更（展開・lint・ドキュメント）は Task 1 と Task 3、deskil-dev の変更（表の 5 か所）は Task 2、未決の `--ref` 検証は Task 3 のバックログ項目。
- 型と名前: `expand_argv`、`DEF_DIR_VAR`、`unknown-variable` は Task 1 で定義し、Task 2 と Task 3 は `${DEF_DIR}` の文字列だけを使う。
- 実行しないステートは Task 2 のテストで固定した。
