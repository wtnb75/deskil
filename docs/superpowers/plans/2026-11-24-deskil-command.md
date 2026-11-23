# `deskil` コマンド化 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** フローエンジンを `uv tool install` で入れる `deskil` コマンド（`deskil flow …`）として配り、プラグインの `flow.py` の symlink をなくす。

**Architecture:** `shared/flow/flow.py` は単一ファイルのまま、版（`__version__`）と `engine` の最小版チェックを足す。同じディレクトリに、サブコマンドを振り分けるだけの `deskil.py` を置く。ルートの `pyproject.toml` が 2 つのモジュールを `deskil` コマンドとして公開する。skill は `deskil flow …` を呼ぶ。

**Tech Stack:** Python 3.11+（標準ライブラリのみ）、setuptools、`uv tool`、pytest、`task`。

**Spec:** `docs/superpowers/specs/2026-11-23-flow-distribution-design.md`（以下「設計書」）

## Global Constraints

- `flow.py` は単一ファイル・標準ライブラリのみ。PEP 723 のヘッダ（`requires-python = ">=3.11"`、`dependencies = []`）を保つ（`tests/test_script_header.py` が見る）。
- エンジンの初版の版は `1.0.0`。`__version__` の出どころは `flow.py` の 1 か所だけ（`__version__ = "1.0.0"` の文字列リテラル）。
- `engine` の書式は `>=MAJOR.MINOR[.PATCH]` だけ。`engine` が無い定義は、版を問わず動く。
- コードのコメント、ログ、エラーメッセージ、`README.md`、skill の本文は英語。`docs/` は日本語。
- 更新の案内文は一字一句これを使う: `run \`uv tool upgrade deskil\``。導入の案内は `uv tool install git+https://github.com/wtnb75/deskil`。
- 導入確認の文（skill の本文に入れる。全 skill で同じ）:
  `Before anything else, run \`deskil --version\`. If the command is not found, tell the user to run \`uv tool install git+https://github.com/wtnb75/deskil\` and stop.`
- `backlog.py` と `common.sh` の symlink は変えない。`Taskfile.yml` の `lint-flow` は `uv run shared/flow/flow.py` のまま。
- コミットメッセージの末尾に、システムの指示にある `Co-Authored-By` と `Claude-Session` の 2 行を付ける。ファイルの削除は `git rm`（追跡済みのもの）で行う。
- 1 回の Bash 呼び出しには単純なコマンド 1 つだけを書く。複数の手順は `Write` でスクリプトを作って実行する。

## Review Focus

設計書が暗に求めているが、どのタスクのテストも直接は見ない入力。各行のテストは、持ち主のタスクに入れてある。

1. `engine` の書式が不正（`"1.4"`、`">1.4"`、`"<=2"`、`">=1.x"`、文字列でない値）: クラッシュせず、`lint` が `engine` の位置に error を出す（Task 1）。
2. 古いエンジンで定義を読む: `lint`（`--format json` も）、`dry-run`、`graph`、`export`、`fmt`、`start` のどれも、定義を誤解釈せず、更新案内つきで非 0 で止まる。`fmt` はファイルを書き換えない（Task 1）。
3. `deskil flow start` が出す `next` のヒントが、そのまま貼れる `deskil flow next …` になる。`FLOW_CMD` が設定されていればそちらが勝つ（Task 2）。
4. `deskil` の引数なし・未知のサブコマンドは、スタックトレースを出さず、使い方を出して非 0 で終わる（Task 2）。
5. リポジトリの外に導入した `deskil` で、`flow new` と `flow lint` が動く（`#:schema` の行が付かなくてもよい）（Task 3）。

---

### Task 1: 版と `engine` の最小版チェック（`flow.py`）

**Files:**
- Modify: `shared/flow/flow.py`（`TOP_KEYS`、`lint_schema`、`lint`、`load_definition`、`NEW_TEMPLATE`、部品の読み込み）
- Modify: `shared/flow/flow.schema.json`
- Create: `tests/test_engine_version.py`

**Interfaces:**
- Produces: `flow.__version__: str`（`"1.0.0"`）、`flow.check_engine(raw: dict) -> None`（満たさなければ `FlowError`。書式が不正・`engine` なしは何もしない。書式の不正は `lint_schema` が報告する）。

- [ ] **Step 1: 失敗するテストを書く（`tests/test_engine_version.py`）**

  `NEW_TEMPLATE` の先頭に `engine = "<値>"` の行を足した定義を `write_def` で書くヘルパ `defn(tmp_path, engine_line)` を使う。

  - `test_version_is_semver`: `flow.__version__ == "1.0.0"`。
  - `test_engine_satisfied_lints_clean`: `engine = ">=1.0"` と `">=1.0.0"` で `flow.lint(path) == []`。
  - `test_engine_missing_is_fine`: `engine` なしで `flow.lint(path) == []`。
  - `test_engine_too_new_stops_the_command`（`@pytest.mark.parametrize` で `lint` / `dry-run` / `graph` / `export` / `fmt` / `start`。`start` は `--state-dir tmp_path/"runs"` を付ける）: `engine = ">=99.0"` で `flow.main([cmd, str(path)])` が `1` を返し、stderr に `needs deskil 99.0 or newer (installed: 1.0.0)` と `run \`uv tool upgrade deskil\`` を含む（`capsys`）。`fmt` はファイルの中身が変わらない。
  - `test_engine_too_new_in_json_lint`: `main(["lint", path, "--format", "json"])` の出力が JSON で、`read-error` の issue に上の更新案内が入る。
  - `test_engine_bad_format_is_a_lint_error`（`@pytest.mark.parametrize` で `"1.4"`、`">1.4"`、`"<=2"`、`">=1.x"`、`">=1."`）と `test_engine_not_a_string`（`engine = 3`）: `flow.lint(path)` に、位置が `engine` の level `error` の issue がある。`main(["dry-run", path])` はクラッシュしない（`FlowError` として終わる）。
  - `test_engine_in_a_part_is_an_error`: `include` で読む部品に `engine = ">=1.0"` があると、`lint` が error を出す（メッセージに `engine is only allowed in the root definition`）。
  - `test_new_template_mentions_engine`: `flow.NEW_TEMPLATE` に `# engine = ">=1.0"` のコメント行がある。かつ `flow new` で作った定義が `flow.lint` を通り、`fmt --check` が差分なしで通る。
  - `test_schema_file_knows_engine`: `flow.schema.json` の `properties.engine.type == "string"`。

- [ ] **Step 2: 失敗を確かめる**

  Run: `uv run --with pytest pytest tests/test_engine_version.py -q`
  Expected: FAIL（`__version__` も `engine` も無い）。

- [ ] **Step 3: 実装する（`shared/flow/flow.py`）**

  - 先頭近くに `__version__ = "1.0.0"`。
  - `TOP_KEYS` に `"engine"` を足す。`lint_schema` に、`engine` があるとき `^>=\s*(\d+)\.(\d+)(?:\.(\d+))?$` に一致する文字列でなければ error（位置 `engine`、メッセージに期待する書式を入れる）。
  - `check_engine(raw: dict) -> None`: 一致したとき、要求する版（足りない桁は 0）が `__version__` より大きければ `FlowError(f"this definition needs deskil {要求の版} or newer (installed: {__version__}); run \`uv tool upgrade deskil\`")`。版は入力どおりの表記（`99.0` なら `99.0`）で出す。
  - `check_engine` を呼ぶ場所: ルート定義を `parse_toml` した直後。`lint`、`load_definition`、および定義を読む他のコマンド（`graph_mermaid`、`export_skill`、`format_definition`、`rename_state`、`run_scenarios`）。取りこぼしがないかは、Step 1 の parametrize が見る（`dry-run` と `start` は `load_definition` を通る）。
  - 部品に `engine` があれば、include を展開する側（`lint_schema(sub_raw, …)` を呼ぶ箇所）で error を出す。ルートだけが持てる。
  - `NEW_TEMPLATE` の `schema = 1` の次に、`# engine = ">=1.0"  # minimum deskil version this definition needs` を足す。
  - `flow.schema.json` に `engine`（`type: string`、`pattern` は上の正規表現と同じ意味）を足す。

- [ ] **Step 4: テストが通ることを確かめる**

  Run: `uv run --with pytest pytest tests -q`
  Expected: PASS（`test_schema_file.py`、`test_fmt.py`、`test_script_header.py` を含め全部）。

- [ ] **Step 5: コミット**

  ```bash
  git add shared/flow/flow.py shared/flow/flow.schema.json tests/test_engine_version.py
  git commit -m "flow: add __version__ and the engine minimum-version check"
  ```

---

### Task 2: `deskil` の入口と、`flow.py` の `prog` / ヒントの切り替え

**Files:**
- Create: `shared/flow/deskil.py`
- Modify: `shared/flow/flow.py`（`_default_cmd`、`_build_parser`、`main`）
- Create: `tests/test_deskil_cli.py`

**Interfaces:**
- Consumes: Task 1 の `flow.__version__`。
- Produces:
  - `flow.main(argv: list[str] | None = None, *, prog: str = "flow", cmd: str | None = None) -> int`。`prog` は `argparse` の `prog`。`cmd` は `next` のヒントの先頭（`FLOW_CMD` 環境変数 → `cmd` → `uv run <argv[0]>` の順で決める）。
  - `deskil.main(argv: list[str] | None = None) -> int`、`deskil.SUBCOMMANDS: dict[str, str]`（サブコマンド名 → 1 行の説明。今は `{"flow": "step-by-step flow runner"}`）。

- [ ] **Step 1: 失敗するテストを書く（`tests/test_deskil_cli.py`）**

  `sys.path` に `shared/flow` は `conftest.py` が入れている。`import deskil` する。
  - `test_version`: `deskil.main(["--version"]) == 0`、stdout が `deskil 1.0.0\n`。
  - `test_no_args_prints_usage`: `deskil.main([]) == 2`、stderr に `usage: deskil` と `flow`。
  - `test_unknown_command`: `deskil.main(["nope"]) == 2`、stderr に `unknown command: nope`。例外は出ない。
  - `test_help_exits_zero`: `deskil.main(["--help"]) == 0`、stdout に `flow`。
  - `test_flow_is_passed_through`: 有効な定義に対し、`deskil.main(["flow", "lint", p])` の戻り値と出力が `flow.main(["lint", p])` と同じ（正常と error の両方の定義で）。
  - `test_flow_help_uses_the_deskil_prog`: `deskil.main(["flow", "--help"])` は `SystemExit(0)`。stdout が `usage: deskil flow` で始まる。
  - `test_next_hint_is_deskil_flow`: `FLOW_CMD` を外した環境で `deskil.main(["flow", "start", p, "--state-dir", d])` の stdout に `deskil flow next ` を含み、`uv run` を含まない。
  - `test_flow_cmd_env_wins`: `FLOW_CMD=custom` のとき、ヒントは `custom next ` で始まる。

- [ ] **Step 2: 失敗を確かめる**

  Run: `uv run --with pytest pytest tests/test_deskil_cli.py -q`
  Expected: FAIL（`deskil` モジュールが無い）。

- [ ] **Step 3: 実装する**

  - `flow.py`: `_default_cmd(cmd: str | None = None)` は `os.environ.get("FLOW_CMD") or cmd or f"uv run …"`。`_build_parser(prog: str = "flow")` が `prog` を使う。`main` が `prog` と `cmd` を受け、`_default_cmd(cmd)` を 3 か所で使う。既存の呼び出し（引数なし）の結果は変わらない（`tests/test_cli.py` の `uv run /opt/p/flow.py next` が通る）。
  - `deskil.py`: `flow` を遅延 import する（`--version` や使い方の表示で、使わないモジュールを読み込まない）。`deskil flow …` は `flow.main(rest, prog="deskil flow", cmd="deskil flow")`。第 1 引数が `--version` なら `deskil <flow.__version__>` を出して 0。`-h` / `--help` は一覧を stdout に出して 0。引数なしと未知のサブコマンドは、使い方を stderr に出して 2（未知は `unknown command: <名前>` を含める）。末尾に `if __name__ == "__main__": raise SystemExit(main())`。

- [ ] **Step 4: テストが通ることを確かめる**

  Run: `uv run --with pytest pytest tests -q`
  Expected: PASS。

- [ ] **Step 5: コミット**

  ```bash
  git add shared/flow/deskil.py shared/flow/flow.py tests/test_deskil_cli.py
  git commit -m "deskil: add the entry point that dispatches to the flow engine"
  ```

---

### Task 3: パッケージ化（`pyproject.toml`）

**Files:**
- Create: `pyproject.toml`
- Modify: `.gitignore`（`build/`、`*.egg-info/`）
- Create: `tests/test_packaging.py`

**Interfaces:**
- Consumes: Task 2 の `deskil.main`、Task 1 の `flow.__version__`。
- Produces: `uv tool install --from <リポジトリ> deskil` で `deskil` コマンドが入る。

- [ ] **Step 1: 失敗するテストを書く（`tests/test_packaging.py`）**

  - `test_pyproject_metadata`（`tomllib`）: `project.name == "deskil"`、`project.scripts == {"deskil": "deskil:main"}`、`project.requires-python == ">=3.11"`、`project.dependencies == []`、`"version"` が `project.dynamic` にある。
  - `test_install_and_run_outside_the_repo`（`@pytest.mark.skipif(shutil.which("uv") is None, reason=...)`）: `UV_TOOL_DIR` と `UV_TOOL_BIN_DIR` を `tmp_path` の下に向けて `uv tool install --from <ROOT> deskil` を実行する。そのあと、`cwd=tmp_path` で次を確かめる。`deskil --version` が `deskil 1.0.0`。`deskil flow new x.toml` が 0。`deskil flow lint x.toml` が 0 で出力が空。`deskil flow new` で作った `x.toml` の先頭が `#:schema` でない（リポジトリの外なので付かない）。

- [ ] **Step 2: 失敗を確かめる**

  Run: `uv run --with pytest pytest tests/test_packaging.py -q`
  Expected: FAIL（`pyproject.toml` が無い）。

- [ ] **Step 3: `pyproject.toml` を書く**

  - `[build-system]`: `requires = ["setuptools>=68"]`、`build-backend = "setuptools.build_meta"`。
  - `[project]`: `name = "deskil"`、`dynamic = ["version"]`、`requires-python = ">=3.11"`、`dependencies = []`、短い英語の `description`、`license` と `readme` は既存のファイルに合わせる、`[project.scripts] deskil = "deskil:main"`。
  - `[tool.setuptools]`: `package-dir = {"" = "shared/flow"}`、`py-modules = ["deskil", "flow"]`。`[tool.setuptools.dynamic]`: `version = {attr = "flow.__version__"}`。
  - **判断（設計書 §5.1 からの変更）:** `flow.schema.json` は同梱しない。`py-modules` では同じディレクトリに置く方法が重く、導入後の `_schema_directive` は、リポジトリの外では元から `#:schema` を付けないため、無くて困らない。同梱しないことは、`pyproject.toml` のコメントに英語で 1 行書く。

- [ ] **Step 4: テストが通ることを確かめる**

  Run: `uv run --with pytest pytest tests -q`
  Expected: PASS（`uv` が無い環境では install のテストだけ SKIP）。

- [ ] **Step 5: コミット**

  ```bash
  git add pyproject.toml .gitignore tests/test_packaging.py
  git commit -m "deskil: package the engine as the deskil command"
  ```

---

### Task 4: `deskil` プラグインの移行

**Files:**
- Delete: `plugins/deskil/scripts/flow.py`（symlink。`git rm`）
- Modify: `plugins/deskil/skills/{flow-author,flow-review,flow-convert,flow-export}/SKILL.md`
- Modify: `plugins/deskil/skills/flow-convert/flow.toml`、`plugins/deskil/skills/flow-export/flow.toml`
- Modify: `tests/test_deskil_plugin.py`

**Interfaces:**
- Consumes: Global Constraints の導入確認の文。

- [ ] **Step 1: テストを新しい期待に書き換える（`tests/test_deskil_plugin.py`）**

  - `test_engine_is_bundled_by_relative_symlink` → `test_no_bundled_engine`: `not (CORE / "scripts" / "flow.py").exists()` かつ `not is_symlink()`。
  - `test_skill_frontmatter`: `allowed-tools == "Bash(deskil flow:*)"`。
  - `test_author_skill_covers_the_authoring_commands`: 必要な文字列を `deskil flow lint` / `deskil flow dry-run` / `deskil flow rename` / `{ file =` にする。
  - `test_flow_driven_skill_runs_its_definition`: `deskil flow start ${CLAUDE_PLUGIN_ROOT}/skills/{skill}/flow.toml`。
  - `test_convert_skill_covers_…`、`test_review_skill_covers_…`、`test_export_skill_covers_…` の `flow.py X` を `deskil flow X` にする。
  - 新規 `test_skills_check_the_install_first`: 4 つの `SKILL.md` すべてに `deskil --version` と `uv tool install git+https://github.com/wtnb75/deskil` がある。
  - 新規 `test_no_engine_path_left`: `plugins/deskil` 以下の `*.md` と `*.toml` に `scripts/flow.py` が無い。
  - 新規 `test_author_and_convert_recommend_the_command_not_a_symlink`: `flow-author/SKILL.md` と `flow-convert/flow.toml` の「skill に組み込むとき」の文に `deskil flow` と `deskil --version` があり、`symlink` が無い。
  - 新規 `test_export_removes_the_deskil_entry`: `flow-export/flow.toml` に `Bash(deskil flow:*)` を `allowed-tools` から外す手順があり、`symlink` が無い。

- [ ] **Step 2: 失敗を確かめる**

  Run: `uv run --with pytest pytest tests/test_deskil_plugin.py -q`
  Expected: FAIL。

- [ ] **Step 3: 移行する**

  - `git rm plugins/deskil/scripts/flow.py`。
  - 4 つの `SKILL.md`: `allowed-tools: Bash(deskil flow:*)`、本文の `uv run ${CLAUDE_PLUGIN_ROOT}/scripts/flow.py X` をすべて `deskil flow X` にし、本文の最初の手順に導入確認の文を置く。
  - `flow-convert/flow.toml` と `flow-export/flow.toml`: notes の「`flow.py <args>` means `uv run …`」を「`flow <args>` means `deskil flow <args>`」の意味に直し、各ステートの `flow.py X` を `deskil flow X` にする。`flow-export` の手順 3・4 は、「`allowed-tools` から `Bash(deskil flow:*)` を外す」に直し、symlink の話は削除する（`flow.toml` を残す理由の文は残す）。
  - `flow-author/SKILL.md` の末尾（組み込み方）と `flow-convert/flow.toml` の同じ趣旨の文: 「`allowed-tools` に `Bash(deskil flow:*)` を足し、本文の最初に導入確認の文を置き、`deskil flow start <flow.toml>` を呼ぶ」に直す。symlink で同梱する説明は削除する。
  - 取りこぼしの確認: `rtk rg 'flow\.py|symlink' plugins/deskil`。残るのは、`run = ["uv", "run", "${DEF_DIR}/…"]` の一般的な例と、部品の共有に使う symlink の説明（flow-author の `include` の文）だけ。

- [ ] **Step 4: テストが通ることを確かめる**

  Run: `uv run --with pytest pytest tests -q`
  Expected: PASS。

- [ ] **Step 5: コミット**

  ```bash
  git add plugins/deskil tests/test_deskil_plugin.py
  git commit -m "deskil plugin: call the deskil command instead of the bundled flow.py"
  ```

---

### Task 5: `deskil-dev` プラグインの移行

**Files:**
- Delete: `plugins/deskil-dev/scripts/flow.py`（symlink。`git rm`）。`backlog.py` は残す。
- Modify: `plugins/deskil-dev/skills/{add,decide,prio,impl,triage-rejected}/SKILL.md`
- Modify: `plugins/deskil-dev/skills/{add,decide,prio,impl}/flow.toml`（notes）
- Modify: `tests/test_deskil_dev_plugin.py`

- [ ] **Step 1: テストを書き換える（`tests/test_deskil_dev_plugin.py`）**

  - `ALLOWED_TOOLS = "Bash(deskil flow:*), Bash(uv run ${CLAUDE_PLUGIN_ROOT}/scripts/backlog.py:*)"`。
  - `run_flow` は `[sys.executable, str(ROOT / "shared" / "flow" / "flow.py"), …]` を実行する。
  - symlink を確かめる parametrize から `flow.py` の行を外す（`backlog.py` は残す）。`test_no_flow_symlink`: `not (DEV / "scripts" / "flow.py").exists()`。
  - `test_skill_runs_the_flow`: `deskil flow start`。notes の文（`backlog.py` と並べて `deskil flow` を書いた文）を確かめているテストは、新しい文に合わせる。
  - 新規 `test_skills_check_the_install_first`: 5 つの `SKILL.md` に `deskil --version` と導入コマンドがある。

- [ ] **Step 2: 失敗を確かめる**

  Run: `uv run --with pytest pytest tests/test_deskil_dev_plugin.py -q`
  Expected: FAIL。

- [ ] **Step 3: 移行する**

  - `git rm plugins/deskil-dev/scripts/flow.py`。
  - 5 つの `SKILL.md`: `allowed-tools` を上の `ALLOWED_TOOLS`、`flow.py start` を `deskil flow start`、本文の最初に導入確認の文。
  - 4 つの `flow.toml` の notes: `` `backlog.py` and `flow.py` still find … `` を `` `backlog.py` and `deskil flow` still find … `` にする。
  - 確認: `rtk rg 'flow\.py' plugins/deskil-dev` に、`flow.py` の実行を指すものが残っていない。

- [ ] **Step 4: テストが通ることを確かめる**

  Run: `uv run --with pytest pytest tests -q`
  Expected: PASS。さらに `task lint-flow` が通る。

- [ ] **Step 5: コミット**

  ```bash
  git add plugins/deskil-dev tests/test_deskil_dev_plugin.py
  git commit -m "deskil-dev plugin: call the deskil command instead of the bundled flow.py"
  ```

---

### Task 6: `feature-a` の移行と、取りこぼしを防ぐテスト

**Files:**
- Delete: `plugins/feature-a/scripts/flow.py`（symlink。`git rm`）。`common.sh` は残す。
- Modify: `plugins/feature-a/skills/review-loop/SKILL.md`
- Modify: `tests/test_e2e.py`
- Create: `tests/test_distribution.py`

- [ ] **Step 1: テストを書く**

  - `tests/test_e2e.py`: `LINK` を `ENGINE = ROOT / "shared" / "flow" / "flow.py"` に置き換え、`run_flow` と `hint_args` はそれを使う。`test_symlink_is_relative_and_points_at_shared_engine` は削除する。`test_skill_runs_the_bundled_script` は `test_skill_runs_the_deskil_command` にし、`allowed-tools: Bash(deskil flow:*)` と `deskil flow start` を確かめる。
  - `tests/test_distribution.py`（新規。`plugins/` 全体を見る）:
    - `test_no_plugin_bundles_the_engine`: `plugins/*/scripts/flow.py` が 1 つも無い。
    - `test_no_skill_text_points_at_the_bundled_engine`: `plugins/` 以下の `SKILL.md` と `flow.toml` に `scripts/flow.py` が無い。
    - `test_every_deskil_flow_skill_checks_the_install`: `deskil flow` を含む `SKILL.md` はすべて、`deskil --version` と導入コマンドを含む。

- [ ] **Step 2: 失敗を確かめる**

  Run: `uv run --with pytest pytest tests/test_e2e.py tests/test_distribution.py -q`
  Expected: FAIL。

- [ ] **Step 3: 移行する**

  - `git rm plugins/feature-a/scripts/flow.py`。
  - `review-loop/SKILL.md`: `allowed-tools: Bash(deskil flow:*)`、`deskil flow start …`、最初に導入確認の文。

- [ ] **Step 4: テストが通ることを確かめる**

  Run: `uv run --with pytest pytest tests -q`
  Expected: PASS（Task 4・5 の移行も済んでいるので `test_distribution.py` が通る）。

- [ ] **Step 5: コミット**

  ```bash
  git add plugins/feature-a tests/test_e2e.py tests/test_distribution.py
  git commit -m "feature-a: call the deskil command; guard against leftover engine copies"
  ```

---

### Task 7: ドキュメントと最終確認

**Files:**
- Modify: `README.md`、`CLAUDE.md`（`project-deskil/CLAUDE.md`）、`.taplo.toml`（コメント）、`docs/superpowers/specs/2026-11-22-flow-engine-design.md`、`docs/superpowers/specs/2026-11-23-flow-distribution-design.md`

- [ ] **Step 1: `README.md`（英語）を直す**

  - 導入の節を足す: `uv tool install git+https://github.com/wtnb75/deskil`、更新は `uv tool upgrade deskil`。
  - コマンド一覧の `uv run flow.py X` を `deskil flow X` に直す。`flow.toml` の `engine = ">=1.0"` の説明（最小のエンジン版。`>=` のみ）を足す。
  - 利用者向けの移行手順（設計書 §5.5 の 3 手順）と、開発者向けの節（`uv tool install --editable .` で、導入済みの `deskil` が作業ツリーのエンジンを使う）を足す。
  - 構成図から `scripts/flow.py` の symlink を外し、`pyproject.toml` と `shared/flow/deskil.py` を足す。symlink の節は `backlog.py` と `common.sh` だけの話にする。

- [ ] **Step 2: その他を直す**

  - `CLAUDE.md` の「共有スクリプト」: 対象を `backlog.py` と `common.sh` にし、`flow.py` は `deskil flow`（開発中は `uv tool install --editable .`）で使うと 1 行足す。
  - `.taplo.toml` のコメントの `flow.py lint` を `deskil flow lint` にする。
  - `flow-engine-design.md` の §3（単一ファイルにする理由が「symlink で同梱するため」）と §6x のファイル構成に、「配布方法は `2026-11-23-flow-distribution-design.md` で変更した」と注記する。
  - `flow-distribution-design.md` の状態を `承認済み` にし、§5.1 の「同梱するもの」から `flow.schema.json` を外して、理由（Task 3 の判断）を 1 行書く。

- [ ] **Step 3: 全体の確認**

  Run: `task test`、`task lint`、`task lint-flow`（それぞれ別の呼び出しで）
  Expected: すべて成功。
  Run: `rtk rg 'scripts/flow\.py' --glob '!docs/**'`
  Expected: 一致なし。

- [ ] **Step 4: 実機の確認（設計書 §8 の最初の条件）**

  `/tmp` に空のリポジトリを作り、`.claude/skills/x/flow.toml`（`deskil flow new` で作ったもの）を置く。`UV_TOOL_DIR` と `UV_TOOL_BIN_DIR` を `/tmp` に向けて `uv tool install --from <このリポジトリ> deskil` をし、`deskil flow start .claude/skills/x/flow.toml` が最初のステップを出し、`next` のヒントが `deskil flow next …` であることを確かめる。`deskil` を PATH から外したときに、skill の導入確認の文どおり止まるかは、テストでは確かめられないので、結果を PR の説明に書く。

- [ ] **Step 5: コミット**

  ```bash
  git add README.md CLAUDE.md .taplo.toml docs
  git commit -m "docs: document the deskil command, its installation and the migration"
  ```
