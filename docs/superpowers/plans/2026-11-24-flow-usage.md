# flow: ステートごとのトークン使用量 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** run のステートごとにトークン使用量を集計・保存し、複数 run の平均を表と Mermaid 図で見られるようにする。

**Architecture:** 新しい標準ライブラリのみのモジュール `shared/flow/usage.py` が、セッションログ（jsonl）の読み取り、ステート区間への振り分け、`usage.json` の読み書き、複数 run の集計、表の整形を持つ。`flow.py` は `Run` に `session_id` / `started_at` を足し、run 終了時に `usage.json` を保存し、`usage` サブコマンドと `graph --usage` を足す。

**Tech Stack:** Python 3.11+（標準ライブラリのみ）、pytest、ruff。

**Spec:** `docs/superpowers/specs/2026-11-24-flow-usage-design.md`

## Global Constraints

- Python 標準ライブラリのみ。定義の形式（flow.toml）は変えない。
- run の状態ファイルは後方互換を保つ。追加項目は省略可能で、無い run は空として読む。
- `shared/` 配下の実体を編集する（`plugins/*/scripts/` のシンボリックリンクは編集しない）。
- ソースコードのコメント・ログ・エラーメッセージ・`README.md` は英語。`docs/` は日本語。
- `--usage` なしの `flow graph` の出力は変えない（`tests/test_graph.py` の既存テストが通る）。
- 集計の失敗で `next` を失敗させない（警告を stderr に出すだけ）。

## Review Focus

- `CLAUDE_CODE_SESSION_ID` が無い環境（手動実行・CI）で `start` / `next` が壊れない。`usage` は「データなし」と明示して失敗する。
- セッションログが消えている run: 保存済み `usage.json` があればそれを使い、無ければ run ID を含むエラーにする。
- `session_id` も `started_at` も無い古い run を `status` / `next` / `usage` で読める。
- ログに壊れた行・`message.id` の無い行・タイムスタンプの無い行があっても落ちない。
- 同じステートに複数回入る run（ループ）で、訪問分が合計され `visits` が実際の回数になる。
- 複数 run のうち、あるステートを通らなかった run がある場合、そのステートの平均は「通った run だけ」で出し、`runs` 欄に通った run 数を出す。

## 設計書からの変更点（1 件）

設計書は `bench/tokens.py` のログ読み取りを共通部品へ切り出すとしていた。ただし `tokens.py` は「単一ファイル・標準ライブラリのみ」の独立スクリプトで、`shared/bench/` は PyPI 配布物（`py-modules = ["deskil", "flow"]`）に入らない。そこで **共通化せず、`usage.py` に時刻付きの読み取りを別に実装する**。メッセージ id ごとに usage を 1 回だけ数える規則は同じにし、コメントでそれを明記する。共通化は、必要になったときにバックログへ追加する。

## ファイル構成

- Create: `shared/flow/usage.py` — ログ読み取り・区間振り分け・保存・集計・整形
- Modify: `shared/flow/flow.py` — `Run` の項目、`start_run`、`_next_step_locked`、`graph_mermaid`、`usage` サブコマンド、`graph --usage`
- Modify: `pyproject.toml` — `py-modules` に `usage` を足す
- Create: `tests/test_usage.py`, `tests/test_usage_cli.py`
- Modify: `tests/test_graph.py`, `tests/test_packaging.py`（`usage` が配布に入る確認）、`docs/BACKLOG.md`

---

### Task 1: セッションログの読み取りとステート区間への振り分け

**Files:**
- Create: `shared/flow/usage.py`
- Test: `tests/test_usage.py`（先頭で `from conftest import ...` は使わず、`conftest.py` が通す `sys.path` で `import usage` する）

**Interfaces:**
- Produces（以降のタスクが使う）:
  - `@dataclass class Bucket`: 整数項目 `input, cache_create, cache_read, output, turns, tool_calls, sub_total`（既定 0）。プロパティ `total`（input+cache_create+cache_read+output）、`all_total`（total+sub_total）。メソッド `add(self, other: "Bucket") -> None`。
  - `@dataclass class Turn`: `ts: datetime`（aware）、`usage: dict`、`tool_calls: int`、`sub: bool`。
  - `read_turns(path: Path, sub: bool = False) -> list[Turn]`
  - `find_session_log(session_id: str, projects_dir: Path | None = None) -> Path | None`
  - `Interval = tuple[str, datetime, datetime | None]`（ステート id、入室、退室。`None` は上限なし）
  - `intervals_of(history: list[dict], started_at: str, status: str, current: str) -> list[Interval]`
  - `split_by_state(turns: list[Turn], intervals: list[Interval]) -> dict[str, Bucket]`

- [ ] **Step 1: 失敗するテストを書く（`tests/test_usage.py`）**

テスト名と検証内容（jsonl はテスト内のヘルパー `_line(ts, mid, usage, blocks)` で `tmp_path` に書く）:
  - `test_read_turns_counts_each_message_id_once`: 同じ `message.id` の 2 行（content block ごとに 1 行、usage は同じ）→ `Turn` は 1 件、`tool_calls` は 2 行の `tool_use` の合計。
  - `test_read_turns_skips_bad_lines`: 壊れた JSON 行、`id` の無い assistant 行、`timestamp` の無い行を混ぜても落ちず、有効な行だけ返る。
  - `test_find_session_log_globs_projects`: `projects_dir/<任意の名前>/<session_id>.jsonl` を見つける。無ければ `None`。`projects_dir` 省略時は `$CLAUDE_CONFIG_DIR/projects`、無ければ `~/.claude/projects`。
  - `test_intervals_of_running_run`: `history=[{"state":"a","at":T1},{"state":"b","at":T2}]`、`started_at=T0`、`status="running"` → `[("a",T0,T1),("b",T1,T2)]` に加えて、現在のステートの区間は `intervals_of` の対象外（現在のステートは次のテストで扱う）。
  - 現在のステートの扱いを決める: `intervals_of` は `history` の各エントリの区間に加えて、`status == "running"` のとき最後の `at`（無ければ `started_at`）から `None` までの区間を、**ステート id を引数で受ける**ため、署名を `intervals_of(history, started_at, status, current)` にする。`test_intervals_of_running_run` は `[("a",T0,T1),("b",T1,T2),("c",T2,None)]`（`current="c"`）を期待する。
  - `test_intervals_of_ended_run_has_no_open_interval`: `status="ended"` のとき、最後のエントリより後の区間は作らない。
  - `test_split_by_state_sums_visits_and_sub`: 同じステート `a` に 2 区間ある run で、各区間のターンの usage と tool_calls が `a` に合算される。`sub=True` のターンは `sub_total` にだけ入り、`turns` には数えない。区間の外のターンは捨てる。境界は「入室 ≤ ts < 退室」。

- [ ] **Step 2: テストが失敗することを確認する**

Run: `uv run pytest tests/test_usage.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'usage'`）

- [ ] **Step 3: `shared/flow/usage.py` に上記の署名で実装する**

署名は上の Interfaces のとおり（`intervals_of` は `current: str` を第 4 引数に足す）。方針:
  - `read_turns`: 行を JSON として読み、`type == "assistant"` で `message.id` と `message.usage`（dict）があるものだけ対象。同じ id は最初の行の `timestamp` を採用し、`usage` は最後の行（出力数が確定している）を採用、`tool_calls` は行ごとの `tool_use` の合計。`timestamp` は `datetime.fromisoformat`（末尾 `Z` は `+00:00` に置換）で読み、読めない行は捨てる。コメントで「`bench/tokens.py` と同じ id ごとの規則」と書く。
  - `find_session_log`: `projects_dir.glob(f"*/{session_id}.jsonl")` の最初の一致。`session_id` は `[A-Za-z0-9_-]+` に合わないなら `None`（パス注入の防止）。
  - `split_by_state`: 各ターンを、入室 ≤ ts < 退室 を満たす最初の区間のステートへ入れる。`sub` のターンは `sub_total += total` のみ。
  - 区間の時刻は `datetime.fromisoformat` で aware にそろえる（`history[].at` はオフセット付き ISO）。

- [ ] **Step 4: テストが通ることを確認する**

Run: `uv run pytest tests/test_usage.py -v`
Expected: PASS（全件）

- [ ] **Step 5: コミット**

```bash
git add shared/flow/usage.py tests/test_usage.py
git commit -m "flow: read session logs and split token usage by state interval"
```

---

### Task 2: `Run` への項目追加と `usage.json` の保存

**Files:**
- Modify: `shared/flow/flow.py`（`Run`: 1476 行付近、`load_run`: 1512 行、`start_run`: 1923 行、`_next_step_locked`: 1986 行）
- Modify: `shared/flow/usage.py`
- Modify: `pyproject.toml`（`py-modules = ["deskil", "flow", "usage"]`）
- Test: `tests/test_usage.py`、`tests/test_runs.py` に追記、`tests/test_packaging.py`

**Interfaces:**
- Consumes: Task 1 の `read_turns`、`find_session_log`、`intervals_of`、`split_by_state`、`Bucket`。
- Produces:
  - `Run.session_id: str = ""`、`Run.started_at: str = ""`（`load_run` は `data.get(..., "")`）。
  - `usage.compute_usage(*, run_id: str, definition: str, definition_hash: str, session_id: str, started_at: str, history: list[dict], visits: dict[str, int], status: str, current: str, projects_dir: Path | None = None) -> dict | None` — ログが見つからない・`session_id` が空のとき `None`。戻り値は設計書の `usage.json` の形（`states.<id>` に `visits, input, cache_create, cache_read, output, turns, tool_calls, sub_total`）。
  - `usage.save_usage(state_dir: Path, run_id: str, data: dict) -> Path`（`<state_dir>/<run_id>/usage.json`、ディレクトリは 0o700、ファイルは 0o600）、`usage.load_usage(state_dir: Path, run_id: str) -> dict | None`（壊れていれば `None`）。
  - `flow._save_usage_on_end(run: Run, state_dir: Path) -> None` — 失敗を握りつぶし、stderr に `warning: could not save usage for run <id>: <reason>` を出す。

- [ ] **Step 1: 失敗するテストを書く**

  - `tests/test_usage.py::test_compute_usage_shape`: 2 ステートの run と偽のログ（`projects_dir` を `tmp_path` に作る）で、`states` のキー・値・`visits`（`visits` 引数の値）が期待どおり。
  - `test_compute_usage_returns_none_without_session_or_log`: `session_id=""`、およびログ無しの 2 通りで `None`。
  - `test_save_and_load_usage_roundtrip`、`test_load_usage_returns_none_for_corrupt_file`。
  - `tests/test_runs.py::test_start_records_session_id_and_started_at`: 環境変数 `CLAUDE_CODE_SESSION_ID=sess1`（`monkeypatch.setenv`）で `start_run` → `load_run` の `session_id == "sess1"`、`started_at` が ISO 文字列。環境変数なしでは `session_id == ""`。
  - `test_load_run_without_new_fields`: 新項目の無い run JSON を読み、空文字になる。
  - `test_next_to_end_saves_usage_json`: `FLOW_PROJECTS_DIR` ではなく、`usage.compute_usage` を `monkeypatch` で固定値を返すものに差し替え、end ステートへの `next` 後に `<state_dir>/<run_id>/usage.json` ができる。差し替えが例外を投げても `next` は成功し、stderr（`capsys`）に `warning: could not save usage` が出る。
  - `tests/test_packaging.py`: `pyproject.toml` の `py-modules` に `usage` があり、`shared/flow/usage.py` が存在する。

- [ ] **Step 2: テストが失敗することを確認する**

Run: `uv run pytest tests/test_usage.py tests/test_runs.py tests/test_packaging.py -v`
Expected: FAIL（新しい関数・項目が無い）

- [ ] **Step 3: 実装する**

  - `usage.py` に `compute_usage`（Task 1 の部品を組み合わせる。メインのログと `<session_id>/subagents/agent-*.jsonl` を `read_turns`、後者は `sub=True`）、`save_usage`、`load_usage` を実装する。サブエージェントのログのパスは、メインのログのパスの拡張子を除いたディレクトリの下（`bench/tokens.py` の `subagent_logs` と同じ配置）。
  - `flow.py`: `Run` に 2 項目を足し（既定値付きなので、既存のコンストラクタ呼び出しはそのまま動く）、`load_run` で読む。`save_run` が JSON 化する方法を確認し、新項目も書かれるようにする。`start_run` で `session_id=os.environ.get("CLAUDE_CODE_SESSION_ID", "")`、`started_at=datetime.now().astimezone().isoformat(timespec="seconds")` を設定する。
  - `_next_step_locked`: `save_run` の直後、`run.status == "ended"` なら `_save_usage_on_end(run, state_dir)` を呼ぶ。ロックを持ったままで構わない。
  - `pyproject.toml` に `usage` を足す。

- [ ] **Step 4: テストが通ることを確認する**

Run: `uv run pytest -q`
Expected: PASS（既存テストを含め全件）

- [ ] **Step 5: コミット**

```bash
git add shared/flow/usage.py shared/flow/flow.py pyproject.toml tests/
git commit -m "flow: record session id and start time; save usage.json when a run ends"
```

---

### Task 3: 複数 run の集計と `usage` サブコマンド

**Files:**
- Modify: `shared/flow/usage.py`、`shared/flow/flow.py`（`_build_parser`: 2969 行、`main`: 3107 行）
- Test: `tests/test_usage.py`（集計・整形）、`tests/test_usage_cli.py`（コマンド）

**Interfaces:**
- Consumes: Task 2 の `compute_usage`、`save_usage`、`load_usage`。
- Produces:
  - `usage.aggregate(usages: list[dict]) -> dict` — `{"runs": N, "states": {id: {"runs": n, "visits_mean": f, "total_mean": f, "total_min": int, "total_max": int, "output_mean": f}}}`。`total` は run 内の `input+cache_create+cache_read+output+sub_total`（`all_total`）。そのステートを通っていない run は、そのステートの平均に入れない（`runs` は通った run 数）。
  - `usage.format_table(agg: dict) -> str` — 列: `state, runs, visits, total(mean), min, max, output(mean), share`。`share` は全ステートの `total_mean` の合計に対する割合（`%`、小数 1 桁）。行は `total_mean` の降順。
  - `flow.load_run_usage(run_id: str, state_dir: Path, save: bool = False) -> dict` — run を読み、`compute_usage` を試し、`None` なら `load_usage`、それも `None` なら `FlowError(f"no usage data for run {run_id}: no session log and no saved usage.json")`。`save=True` で計算結果を `save_usage` する（保存済みを読んだだけなら何もしない）。
  - CLI: `usage RUN_ID [RUN_ID ...] [--save] [--json]`（`parents=[common]`）。出力は既定で `format_table`、`--json` は `aggregate` の結果に各 run の `usage` を `"per_run"` として添えた JSON。

- [ ] **Step 1: 失敗するテストを書く**

  - `test_aggregate_means_over_runs_that_visited`: 3 run のうち 1 run が `x` を通らない → `x` の `runs == 2`、`total_mean` は通った 2 run の平均、`min/max` も 2 run の値。
  - `test_aggregate_includes_sub_total`: `sub_total` が `total` に加算される。
  - `test_format_table_sorted_by_total_desc_with_share`: 行順と、`share` の合計が約 100.0 になる。
  - `tests/test_usage_cli.py::test_usage_command_two_runs_prints_table`: `usage.json` を 2 run 分、`<state_dir>/<id>/usage.json` に直接置き（ログ無し）、run ファイルも用意して `flow.main(["usage", "r1", "r2", "--state-dir", str(d)])` が 0 を返し、stdout に両 run の平均が出る。
  - `test_usage_command_json_has_per_run`、`test_usage_unknown_run_exits_1`（`error: run not found: ...`）、`test_usage_without_any_data_names_the_run`（run はあるがログも `usage.json` も無い → exit 1、メッセージに run ID）。
  - `test_usage_save_writes_usage_json`: `compute_usage` を差し替えて固定値を返し、`--save` で `usage.json` ができる。

- [ ] **Step 2: テストが失敗することを確認する**

Run: `uv run pytest tests/test_usage.py tests/test_usage_cli.py -v`
Expected: FAIL

- [ ] **Step 3: 実装する**

`aggregate`・`format_table` を `usage.py` に、`load_run_usage` とサブコマンドの登録・分岐を `flow.py` に置く。`main` の `state_dir` 解決後の分岐に `elif args.command == "usage":` を足し、`out` を作る形にする（他のコマンドと同じ）。`bench/tokens.py` の表の体裁は踏襲しなくてよい。

- [ ] **Step 4: テストが通ることを確認する**

Run: `uv run pytest -q`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add shared/flow/usage.py shared/flow/flow.py tests/
git commit -m "flow: add the usage command to aggregate token usage over runs"
```

---

### Task 4: `flow graph --usage`

**Files:**
- Modify: `shared/flow/flow.py`（`graph_mermaid`: 2383 行、`graph` のパーサ: 3063 行、`main` の graph 分岐: 3126 行）
- Test: `tests/test_graph.py`

**Interfaces:**
- Consumes: Task 3 の `usage.aggregate`、`flow.load_run_usage`。
- Produces: `graph_mermaid(defn_path: Path, usage_agg: dict | None = None) -> str`。CLI: `graph DEFINITION [--usage RUN_ID ...] [--state-dir DIR]`（`parents=[common]` を足す）。

- [ ] **Step 1: 失敗するテストを書く（既存の `DEF` を使う）**

  - 既存テストが無変更で通る（`usage_agg=None` の出力は今と同一）。
  - `test_graph_usage_labels_and_classes`: `usage_agg = {"runs": 2, "states": {"a": {..., "total_mean": 30000.0, "visits_mean": 2.0}, "w": {..., "total_mean": 10000.0, ...}}}` で、ノード行が `n_a["a<br/>30.0k tokens<br/>2.0 visits"]` の形になり、`class n_a heat4`、`class n_w heat2` のような行が付く。`end` のようにデータの無いステートは今と同じ行で、`class` も付かない。
  - `test_graph_usage_classdefs_present`: `classDef heat1 …` から `heat4` までが出る（段階は `share` の 0〜25%・25〜50%・50〜75%・75〜100% を `heat1..heat4`、0 より大きいが最小段階の未満は `heat1`）。
  - `test_graph_command_usage_flag`: run を用意して `flow.main(["graph", str(defn), "--usage", "r1", "--state-dir", str(d)])` の stdout に `classDef` が出る。

- [ ] **Step 2: テストが失敗することを確認する**

Run: `uv run pytest tests/test_graph.py -v`
Expected: FAIL

- [ ] **Step 3: 実装する**

トークン量の表記は `1234` → `1.2k`、`1234567` → `1.2M`（小さい値はそのまま）。ラベルの 2 行目以降は `<br/>` で足す。段階の判定は、そのステートの `total_mean` を全ステートの `total_mean` の合計で割った割合で行い、`classDef heat1..heat4` の色は Mermaid の `fill` で淡色から濃色にする（文字色は暗い色に固定して、どの段階でも読めるようにする）。`main` の graph 分岐は、`args.usage` があるときだけ `_resolve_state_dir`、`load_run_usage`、`usage.aggregate` を呼ぶ。

- [ ] **Step 4: テストが通ることを確認する**

Run: `uv run pytest -q`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add shared/flow/flow.py tests/test_graph.py
git commit -m "flow: overlay token usage on the graph with --usage"
```

---

### Task 5: ドキュメントとバックログ、最終確認

**Files:**
- Modify: `docs/BACKLOG.md`、利用者向けの flow のコマンド一覧を持つ文書（`rg -l "flow graph" --glob '*.md'` で探す）
- Modify: `tests/test_distribution.py` 等、コマンド一覧を検査するテストがあれば追随

- [ ] **Step 1: コマンド一覧の文書を探して、`usage` と `graph --usage` を追記する**

`rg -n "flow graph|deskil flow graph" --glob '*.md' .` で見つかる、コマンドを列挙している箇所に 1〜2 行ずつ足す（`README.md` は英語、`docs/` は日本語）。`usage.json` の置き場所（`<state-dir>/<run_id>/usage.json`）と、`gc` が run と一緒に消すことを書く。

- [ ] **Step 2: `docs/BACKLOG.md` に 2 件を `docs/BACKLOG.md` 冒頭の書式で追記する**（`deskil-dev:add` と同じ書式。ID は既存の最大値の次から）
  - 「flow: `usage` のログ読み取りを `bench/tokens.py` と共通化する」（見送った理由: 配布物に入るモジュールと独立スクリプトの分離）
  - 「flow: 最適化スキル（`usage.json` と定義を読んで改善案を出す）」（この機能のデータを使う次の作業）
  - B-007 の「実行履歴の重ね表示はしない」の判断の末尾に、`graph --usage` で置き換えた旨を足す。

- [ ] **Step 3: 全体を確認する**

Run: `uv run ruff check . && uv run ruff format --check . && uv run pytest -q`
Expected: エラーなし、全テスト PASS

- [ ] **Step 4: 実機の確認**

このリポジトリで定義を 1 つ `start`〜end まで進め、`deskil flow usage <run_id>` と `deskil flow graph <定義> --usage <run_id>` を実行して、表と図が出ることを確認する（セッションログが実在する Claude Code のセッション内で行う）。結果（ステート別の合計が、`bench/tokens.py` でセッション全体を集計した値を超えないこと）を報告に書く。

- [ ] **Step 5: コミット**

```bash
git add docs README.md
git commit -m "docs: document the usage command and graph --usage; add backlog items"
```
