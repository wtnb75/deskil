# flow: run のタイムライン表示 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `deskil flow timeline RUN_ID...` が、複数 run を同じ時間軸で並べた自己完結の HTML を書き出す。サブエージェントごとの時間とトークン量も記録する。

**Architecture:** `usage.py` が訪問ごとの `timeline`（サブエージェントごとの内訳つき）を作って `usage.json` に入れる。新しい `timeline.py` が、`timeline` から描画データを作り、承認済みの見本（HTML/CSS/JS）を雛形にした単一の HTML を作る。`flow.py` は run の読み込みとサブコマンドの配線だけを持つ。

**Tech Stack:** Python 3.11+（標準ライブラリのみ）、素の HTML/CSS/JS（外部の通信・ライブラリ・Web フォントなし）、pytest、ruff。

**Spec:** `docs/superpowers/specs/2026-11-24-flow-timeline-design.md`（見本: `docs/superpowers/specs/2026-11-24-flow-timeline-mock.html`）

## Global Constraints

- 標準ライブラリのみ。`usage.json` の既存の項目（`states` など）は変えない（後方互換）。
- 出力の HTML に、`http://` または `https://` で始まる外部の参照を入れない（Web フォントも使わない。フォントはシステムのものだけ）。
- コメント・エラーメッセージ・README・HTML 内の表示文言は英語。`docs/` は日本語。
- `shared/` 配下の実体を編集する（`plugins/*/scripts/` のリンクは編集しない）。
- 集計の失敗で `next` を失敗させない（既存の `_save_usage_on_end` の方針のまま）。
- 時刻の比較は `入室 ≤ ts < 退室`（既存の規則）。
- コミットメッセージの末尾に、次の 2 行を付ける:
  `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`
  `Claude-Session: https://claude.ai/code/session_017XuJB7iWyEPcANBscDb9GF`

## Review Focus

- ステート名・サブエージェント名に `</script>`、`<!--`、`"`、`&` が入っても、HTML が壊れず、データが元のまま読める（名前は `usage.json` の run を作る側が決めるので、信頼しない）。
- ログが消えていて、`usage.json` も無い run（`history` はある）で、時刻だけのタイムラインが出る。`started_at` が空の古い run でも落ちない。
- 実行中の run の現在のステート（`open`）が、終了を「今」として描かれる。
- 1 つのサブエージェントが 2 つの訪問にまたがるとき、2 つの項目に分かれ、各訪問の `sub_total` がその訪問の `agents` の合計と一致する。
- 時間 0 秒の訪問、トークン 0 の訪問、訪問が 0 件の run で、HTML の描画（JS）がゼロ除算や `NaN` を出さない。
- トークンが不明（`null`）の訪問が、0 として描かれず「不明」と分かる。
- 出力ファイルを書けない場合（権限、存在しないディレクトリ）に、トレースバックでなく `error:` の 1 行で終わる。

---

## ファイル構成

- Modify: `shared/flow/usage.py` — `timeline` の生成（`build_timeline`、`timeline_from_history`）、`compute_usage` への追加
- Create: `shared/flow/timeline.py` — 描画データ（`build_view`）と HTML（`render_html`）
- Modify: `shared/flow/flow.py` — `load_run_timeline`、`timeline_text`、サブコマンド
- Modify: `pyproject.toml` — `py-modules` に `timeline`
- Create: `tests/test_timeline_data.py`（Task 1–2）、`tests/test_timeline_html.py`（Task 3）、`tests/test_timeline_cli.py`（Task 4）
- Modify: `README.md`、`docs/BACKLOG.md`、`tests/test_packaging.py`

---

### Task 1: 訪問ごとの `timeline`（サブエージェントごとの内訳つき）

**Files:**
- Modify: `shared/flow/usage.py`（`intervals_of` の近く）
- Test: `tests/test_timeline_data.py`

**Interfaces:**
- Consumes（既存）: `Turn`、`Bucket`、`_parse_time`、`_count`、`read_turns`。
- Produces:
  - `timeline_intervals(history: list[dict], started_at: str, status: str, current: str, now: datetime) -> list[dict]` — 各要素は `{"state": str, "visit": int, "start": datetime, "end": datetime, "gate": bool, "open": bool}`。`visit` はそのステートの何回目の訪問か（1 始まり）。`gate` は対応する `history` エントリに `approval` があるか。実行中の run の現在のステートは `end = now`、`open = True`。終了済みの終端ステートは作らない。時刻が読めないエントリは捨てる（`intervals_of` と同じ）。
  - `sum_turns(turns: list[Turn]) -> Bucket` — `turns` と `tool_calls` も数える（サブエージェントのログのターンは `sub=False` で読んだものを渡す）。
  - `build_timeline(*, history, started_at, status, current, turns: list[Turn], agents: dict[str, list[Turn]], now: datetime) -> list[dict]` — 設計書の `timeline` の形（`start` / `end` はミリ秒つきの ISO 文字列）。メインのターンは `start ≤ ts < end`（`open` のときは `end` を無限大として）で振り分け、各 `agents[name]` も同じ規則で振り分けて、ターンの無いエージェントは載せない。エージェントの `start` / `end` は、その訪問内のターンの最初と最後の時刻。`sub_total` は、その訪問の `agents` の合計トークン（`input + cache_create + cache_read + output`）。
  - `timeline_from_history(*, history, started_at, status, current, now) -> list[dict]` — 同じ形で、トークンの項目を `None`、`agents` を空にしたもの（ログが無い run 用）。

- [ ] **Step 1: 失敗するテストを書く（`tests/test_timeline_data.py`）**

テスト名と検証内容:
  - `test_timeline_intervals_marks_gate_and_visit_numbers`: `history` の 1 件に `"approval": "ok"` を持たせ、同じステートに 2 回入る run で、`gate` と `visit`（1, 2）が正しい。
  - `test_timeline_intervals_open_state_ends_now`: `status="running"` の現在のステートは `open=True` で `end == now`。`status="ended"` では作らない。
  - `test_timeline_intervals_drops_unreadable_times_and_empty_started_at`: `started_at=""` のとき最初の訪問が出ない。
  - `test_build_timeline_splits_main_turns_per_visit`: 2 訪問の境界（`ts == end` は次の訪問）で入力・出力・ターン数・ツール呼び出し数が振り分けられる。
  - `test_build_timeline_agent_spanning_two_visits_is_split`: 1 つのエージェントのターンが 2 訪問にまたがり、各訪問に別の項目として載る。各訪問で `sub_total` が `agents` の合計と一致する。
  - `test_build_timeline_agent_start_end_are_first_and_last_turn_in_visit`
  - `test_build_timeline_omits_agents_without_turns_in_a_visit`
  - `test_timeline_from_history_has_none_tokens`: 時刻と `gate` は入り、`input` などが `None`、`agents == []`。

- [ ] **Step 2: テストが失敗することを確認する**

Run: `uv run pytest tests/test_timeline_data.py -v`
Expected: FAIL（`AttributeError` または `ImportError`）

- [ ] **Step 3: `shared/flow/usage.py` に上記の署名で実装する**

`start` / `end` の文字列は `datetime.isoformat(timespec="milliseconds")`。`sum_turns` は `split_by_state` の中の `Bucket` の作り方（`_count` で 4 つの項目）に合わせる。`build_timeline` は `timeline_intervals` を 1 度だけ呼ぶ。

- [ ] **Step 4: テストが通ることを確認する**

Run: `uv run pytest tests/test_timeline_data.py -v`
Expected: PASS（全件）

- [ ] **Step 5: コミット**

```bash
git add shared/flow/usage.py tests/test_timeline_data.py
git commit -m "flow: build per-visit timelines with per-subagent usage"
```

---

### Task 2: `compute_usage` に `timeline` を入れる

**Files:**
- Modify: `shared/flow/usage.py`（`compute_usage`）、`shared/flow/flow.py`（`compute_usage` を呼ぶ 2 か所は変更不要。確認のみ）
- Test: `tests/test_timeline_data.py`

**Interfaces:**
- Consumes: Task 1 の `build_timeline`。
- Produces:
  - `agent_logs(main_log: Path) -> list[Path]` — `<main_log without .jsonl>/subagents/agent-*.jsonl`（並べ替え済み）。
  - `compute_usage(..., now: datetime | None = None)` — 戻り値に最上位の `"timeline"` を足す（`now` 省略時は現在時刻）。エージェント名はファイル名の拡張子を除いたもの（例: `agent-a1b2`）。`states` の中身は変えない。

- [ ] **Step 1: 失敗するテストを書く**
  - `test_compute_usage_includes_timeline`: `projects_dir` の偽ログ（メイン 1 本とサブエージェント 2 本）で、`timeline` の訪問数、`agents` の名前、各訪問の `sub_total` が `states[...]["sub_total"]` の合計と一致する。
  - `test_compute_usage_states_unchanged`: 既存の `states` の値がこれまでと同じ（既存の `tests/test_usage.py` が通ること）。
  - `test_compute_usage_timeline_agent_name_is_file_stem`

- [ ] **Step 2: 失敗を確認する**

Run: `uv run pytest tests/test_timeline_data.py tests/test_usage.py -v`
Expected: 新しいテストが FAIL

- [ ] **Step 3: 実装する**

`compute_usage` で、メインのログは `read_turns(log)`、サブエージェントは `agent_logs(log)` の各ファイルを `read_turns(path, sub=False)` で別々に読んで `agents[path.stem]` に入れる。`states` 用の既存の集計（`sub=True` のターンを混ぜて `split_by_state`）はそのまま残し、`timeline` だけ `build_timeline` で作る。

- [ ] **Step 4: テストが通ることを確認する**

Run: `uv run pytest -q`
Expected: PASS（全件）

- [ ] **Step 5: コミット**

```bash
git add shared/flow/usage.py tests/test_timeline_data.py
git commit -m "flow: record the per-visit timeline in usage.json"
```

---

### Task 3: 描画データと HTML（`timeline.py`）

**Files:**
- Create: `shared/flow/timeline.py`
- Modify: `pyproject.toml`（`py-modules = ["deskil", "flow", "usage", "timeline"]`）、`tests/test_packaging.py`
- Test: `tests/test_timeline_html.py`

**Interfaces:**
- Consumes: Task 1–2 の `timeline` の形（辞書のリスト）。
- Produces:
  - `build_view(*, run_id: str, definition: str, timeline: list[dict]) -> dict` — `{"id": run_id, "note": <definition の末尾 2 要素のパス>, "total_sec": float, "tokens": int, "wait_sec": float, "visits": [{"state", "label", "sec": float, "tok": int, "gate": bool, "known": bool, "subs": [[name, offset_sec, dur_sec, tok], ...]}]}`。`label` は、そのステートが複数回出るときだけ `state #n`。`sec` は `end - start`（負は 0）、`tok` はそのステート自身のセッションのトークン合計（`None` のときは `0` で `known=False`）。`subs` の `offset_sec` は `agent.start - visit.start`（0 以上に丸める）、`dur_sec` は `max(1, agent.end - agent.start)`、`offset + dur` が `sec` を超えるときは `offset` を詰めて収める（`sec` が 0 なら空）。`tokens` はサブエージェント込みの全体、`wait_sec` は `gate` の `sec` の合計。
  - `render_html(views: list[dict]) -> str` — 完結した HTML 文書（`<!doctype html>`、`<html lang="en">`、`<meta charset>`、`<meta name="viewport">`、`<title>Flow Timeline</title>`）。描画データは `<script type="application/json" id="data">` に、`<` を `<`、`>` を `>`、`&` を `&` にエスケープして埋め込む。

- [ ] **Step 1: 失敗するテストを書く（`tests/test_timeline_html.py`）**
  - `test_build_view_labels_repeated_states_with_visit_number`
  - `test_build_view_totals_include_subagents`: `tokens` が（自身＋サブエージェント）の合計、`wait_sec` が gate の合計。
  - `test_build_view_none_tokens_are_unknown_not_zero`: `known == False`。
  - `test_build_view_clamps_subagent_offsets_into_the_visit`
  - `test_build_view_zero_length_visit_has_no_subs`
  - `test_build_view_empty_timeline`: 訪問 0 件で `total_sec == 0`、`visits == []`。
  - `test_render_html_embeds_data_that_roundtrips`: 出力から `id="data"` の `<script>` の中身を取り出し、`json.loads` して、元の `views` と等しい（名前に `</script>`、`<!--`、`"`、`&`、日本語を入れて確かめる）。
  - `test_render_html_has_no_external_references`: 出力に `http://` と `https://` が含まれない。
  - `test_render_html_is_a_complete_document`: `<!doctype html>`、`<title>Flow Timeline</title>`、`prefers-color-scheme` を含む。
  - `test_render_html_handles_no_runs`: `views=[]` でも文書を返す。
  - `tests/test_packaging.py`: `timeline` が `py-modules` に入っている。

- [ ] **Step 2: 失敗を確認する**

Run: `uv run pytest tests/test_timeline_html.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'timeline'`）

- [ ] **Step 3: `shared/flow/timeline.py` を実装する**

雛形は、見本（`docs/superpowers/specs/2026-11-24-flow-timeline-mock.html`）の CSS と JS を、生の文字列（`r"""..."""`）の定数 `_TEMPLATE` に写し、次の点だけ変える。
  - Google Fonts の `<link>` と、`--sans` / `--mono` の `IBM Plex` を外し、システムのフォントだけのスタックにする。
  - ダミーの `RUNS` を、`document.getElementById("data")` の JSON から作る（`visits` の各要素を `[state, sec, tok, gate, subs]` に写し、`known` が偽の訪問は棒を描かず、点線の枠に「tokens unknown」とだけ出す）。
  - ステート名の色は、見本の 6 色を、出現順に割り当て（6 色を超えたら使い回す）。凡例は埋め込みデータのステート名から作る。
  - 描画のゼロ除算を避ける: 全体の最大 `rate`・最大 `span` が 0 のときは 1 とみなす。訪問が 0 件の run は「No visits」と出す。
  - 出力文書の `<title>`、`lang`、`meta` をつける（見本は公開基盤の外枠に任せていた部分）。
  `render_html` は、`_TEMPLATE` の `__DATA__` を、エスケープした JSON で置き換える。

- [ ] **Step 4: テストが通ることを確認する**

Run: `uv run pytest tests/test_timeline_html.py tests/test_packaging.py -v`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add shared/flow/timeline.py pyproject.toml tests/test_timeline_html.py tests/test_packaging.py
git commit -m "flow: render the timeline as a self-contained HTML page"
```

---

### Task 4: `timeline` サブコマンド

**Files:**
- Modify: `shared/flow/flow.py`（`import timeline`、`load_run_usage` の近くに追加、`_build_parser`、`main`）
- Test: `tests/test_timeline_cli.py`

**Interfaces:**
- Consumes: Task 1–3 の `usage.compute_usage` / `usage.load_usage` / `usage.timeline_from_history`、`timeline.build_view`、`timeline.render_html`。
- Produces:
  - `load_run_timeline(run_id: str, state_dir: Path) -> dict` — 戻り値は `{"run_id", "definition", "timeline"}`。順に試す: ① `usage.compute_usage(...)`（ログがある）の `timeline`、② 保存済みの `usage.json` に `timeline` がある、③ `usage.timeline_from_history(...)`（時刻だけ）。run が無ければ既存の「run not found」の `FlowError`。
  - `timeline_text(run_ids: list[str], state_dir: Path, output: str, open_browser: bool, as_json: bool) -> str` — `as_json` なら描画データ（`{"runs": [view, ...]}`）の JSON（`ensure_ascii=False`、`indent=2`）を返す。そうでなければ HTML を作り、`output == "-"` ならその HTML を返し、それ以外は `output` に書いて（親ディレクトリは作らない）書いたパス＋改行を返す。`open_browser` が真なら `webbrowser.open(file URI)`（失敗は無視）。書けないときは `FlowError(f"cannot write {output}: {e.strerror}")`。
  - CLI: `timeline RUN_ID [RUN_ID ...] [-o FILE] [--open] [--json]`（`parents=[common]`）。`-o` の既定は `flow-timeline.html`。

- [ ] **Step 1: 失敗するテストを書く（`tests/test_timeline_cli.py`）**
  - `test_timeline_writes_html_and_prints_path`: `usage.json`（`timeline` つき）を 2 run 分置き、`flow.main(["timeline", "r1", "r2", "-o", str(out), "--state-dir", str(d)])` が 0 で、`out` の中身が HTML で、両 run の ID を含み、標準出力がそのパス。
  - `test_timeline_output_dash_prints_html`
  - `test_timeline_json_prints_views`
  - `test_timeline_falls_back_to_history_without_log_or_usage_json`: `usage.json` も無く、ログも無い run（`history` あり）が、時刻だけの 1 件以上の訪問で出る（`known == False`）。
  - `test_timeline_prefers_computed_over_saved`（`usage.compute_usage` を差し替え）。
  - `test_timeline_unknown_run_exits_1`（`error:` で始まる stderr）。
  - `test_timeline_unwritable_output_is_an_error_line`: 存在しないディレクトリへの `-o` で終了コード 1、stderr が `error: cannot write`。
  - `test_timeline_open_flag_calls_webbrowser_and_ignores_failure`（`webbrowser.open` を差し替え、例外を投げさせても成功する）。

- [ ] **Step 2: 失敗を確認する**

Run: `uv run pytest tests/test_timeline_cli.py -v`
Expected: FAIL（`invalid choice: 'timeline'`）

- [ ] **Step 3: 実装する**

`load_run_usage` の前半（`load_run` と `compute_usage` の呼び出し）と同じ引数で `compute_usage` を呼ぶ（共通の小さな関数にまとめてよい）。`main` の `usage` の分岐の隣に `timeline` の分岐を足す。`state_dir` の解決と `FlowError` の処理は既存のまま。

- [ ] **Step 4: テストが通ることを確認する**

Run: `uv run pytest -q`
Expected: PASS（全件）

- [ ] **Step 5: コミット**

```bash
git add shared/flow/flow.py tests/test_timeline_cli.py
git commit -m "flow: add the timeline command"
```

---

### Task 5: ドキュメントと実機の確認

**Files:**
- Modify: `README.md`、`docs/BACKLOG.md`（必要なら）

- [ ] **Step 1: `README.md` の `usage` の説明の近くに `timeline` を足す**（英語）。コマンドの形、出力が単一の HTML でオフラインで開けること、読み方（幅は時間、高さは 1 分あたりのトークン、面積がトークン量、斜線は人の待ち、点線の箱はサブエージェントを含むステート全体）、`usage.json` に `timeline` が入ること、既存の制限（B-070、B-071）。

- [ ] **Step 2: `docs/BACKLOG.md` を確認する**。`timeline` に関する見送りがあれば、バックログの書式で足す（例: ステート数が多いときの色の見分け、サブエージェントの表示名）。無ければ変更しない。

- [ ] **Step 3: 全体を確認する**

Run: `uv run ruff check . && uv run ruff format --check . && uv run pytest -q`
Expected: エラーなし、全テスト PASS

- [ ] **Step 4: 実機の確認**

このリポジトリの定義で、`start`〜end まで run を 1 つ進め（`FLOW_STATE_DIR` を `/tmp` 配下に向ける）、`uv run shared/flow/flow.py timeline <run_id> --state-dir <dir> -o /tmp/<名前>.html --json` と、`-o` つき（HTML）の両方を実行する。`--json` の出力が JSON として読め、HTML の `id="data"` の中身が同じ内容であること、`https://` が含まれないことを確かめて、結果を報告する。ブラウザでの見た目の確認は、書き出した HTML のパスを報告し、人間が開いて行う（ここでは行わない）。

- [ ] **Step 5: コミット**

```bash
git add README.md docs
git commit -m "docs: document the timeline command"
```
