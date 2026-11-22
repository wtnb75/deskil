# impl に実装後のレビューを入れる 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `impl` の flow に、`verify` 通過後・`commit` 前の自動レビュー（1 周）と、却下した指摘の記録を足す。

**Architecture:** `plugins/deskil-dev/skills/impl/flow.toml` に `classify` / `review` / `security_review` / `triage` / `record_rejected` の 5 状態を足す。`security-review` は返答の形式が独自で flow が止まりやすいので、独立した状態にし、無条件に `triage` へ進める。`classify` に `max_visits = 1` と `on_exceed = "record_rejected"` を付け、直した後の `verify` 通過ではレビューを繰り返さない。却下の記録は `docs/REVIEW-REJECTED.md` に追記する。

**Tech Stack:** flow.toml、pytest（`tests/test_deskil_dev_plugin.py`）。

**Spec:** `docs/superpowers/specs/2026-11-22-impl-review-design.md`

## Global Constraints

- flow のプロンプトは英語。`docs/` の文書（`REVIEW-REJECTED.md` の本文を含む）は日本語。
- `impl` は途中でユーザーに聞かない。採否は自動で決める。
- レビューは 1 周のみ。2 周目と、直した結果への再レビューはしない。
- 既存の状態（`verify` の fail → `fix`、`max_visits = 2`）は変えない。
- `uv run --with pytest pytest tests -q` と `uv run --with ruff ruff check .` が通ること。
- `flow lint` が `impl/flow.toml` でエラーも警告も出さない。

## Review Focus

- `security-review` の報告の形式に引きずられて flow が止まる: `security_review` は `goto = "triage"` だけを持ち、プロンプトが「報告は終わりではない。質問せず、すぐ `next` を実行する」と明示する。
- 直した後の `verify` 通過で、レビューが繰り返されない（`classify` の上限超過で `record_rejected` へ進む）。
- レビュー不要な変更（ドキュメントやバックログだけ）では、`review` を飛ばして `commit` へ進む。
- 指摘を何も直さなかった場合でも、却下した指摘があれば `record_rejected` で記録される。
- 却下がなければ、`docs/REVIEW-REJECTED.md` を作らない・変更しない。
- `verify` の失敗が 2 回を超えたときの `report_fail`（PR を作らない）は、今までどおり。

---

### Task 1: impl の flow に classify / review / security_review / triage / record_rejected を足す

**Files:**
- Modify: `plugins/deskil-dev/skills/impl/flow.toml`
- Test: `tests/test_deskil_dev_plugin.py`

**Interfaces:**
- Produces: 状態 `classify`、`review`、`security_review`、`triage`、`record_rejected`。
  - `verify` の `pass` の行き先: `commit` → `classify`
  - `classify`: `run = ["git", "status", "--porcelain"]`、`max_visits = 1`、`on_exceed = "record_rejected"`。choices は `review`（→ `review`）と `skip`（→ `commit`）。
  - `review`: choices は `security`（→ `security_review`）と `no_security`（→ `triage`）。
  - `security_review`: `goto = "triage"` のみ（choices なし）。
  - `triage`: choices は `fixed`（→ `verify`）と `not_fixed`（→ `record_rejected`）。
  - `record_rejected`: `goto = "commit"`。

- [ ] **Step 1: 失敗するテストを書く（`tests/test_deskil_dev_plugin.py`）**
  - 既存の `test_implement_happy_path_order` を直す。`dry_run("impl", ["found", "pass", "skip"], tmp_path)` の訪問順が `pick, prepare, plan, implement, verify, classify, commit, open_pr, finish_backlog, report`。
  - 追加: `test_implement_review_without_security_or_fixes`。結果 `["found", "pass", "review", "no_security", "not_fixed"]` の訪問順が `... verify, classify, review, triage, record_rejected, commit, open_pr, ...`。
  - 追加: `test_implement_review_with_security`。結果 `["found", "pass", "review", "security", "not_fixed"]` の訪問順が `... classify, review, security_review, triage, record_rejected, commit, ...`。`security_review` の直後は必ず `triage`。
  - 追加: `test_implement_review_with_fixes_reviews_once`。結果 `["found", "pass", "review", "no_security", "fixed", "pass"]` の訪問順が `... verify, classify, review, triage, verify, classify, record_rejected, commit, ...` で、`review` と `triage` は 1 回だけ。（2 回目の `classify` は上限超過で `record_rejected` へ進む。dry-run が上限超過の `classify` を出力しない場合は、その表示に合わせて期待値を直し、ledger に書く。）
  - 追加: `test_implement_review_failure_after_fix_uses_the_fix_limit`。`["found", "pass", "review", "no_security", "fixed", "fail", "fail", "fail"]` の末尾が `report_fail`、`open_pr` を含まない。
  - 追加: `test_security_review_cannot_stall_the_flow`。`security_review` は `choices` を持たず `goto == "triage"`。プロンプトが `security-review` を含み、報告は終わりではないこと（`not the end`）、質問しないこと（`do not ask`）、すぐ `next` を実行すること（`next`）を含む。
  - 追加: `test_classify_runs_git_status`。`flow_states("impl")["classify"]["run"] == ["git", "status", "--porcelain"]`、`max_visits == 1`、`on_exceed == "record_rejected"`。
  - 追加: `test_review_prompt_names_the_reviews`。`review` のプロンプトが `code-review`、`simplify`、`deskil:flow-review` を含み、採否の判断をしない旨（`do not decide`）を含む。
  - 追加: `test_triage_prompt_fixes_once`。`triage` のプロンプトが「once」の趣旨の語と、採用の基準（`out of scope` で却下）を含む。
  - 追加: `test_record_rejected_prompt_covers_the_file`。`record_rejected` のプロンプトが `docs/REVIEW-REJECTED.md` と、却下がなければ何もしない旨（`nothing`）を含む。
  - 既存の `test_flow_lints_clean[impl]` が通ること。

- [ ] **Step 2: テストが失敗することを確認する**

  Run: `uv run --with pytest pytest tests/test_deskil_dev_plugin.py -q`
  Expected: 追加・変更したテストが FAIL（状態がない、`verify` の行き先が違う）。

- [ ] **Step 3: `impl/flow.toml` を編集する**
  - `verify` の `pass` の `goto` を `classify` にする。
  - `classify` を足す。プロンプトは次の趣旨（英語）: `run` の結果（変更ファイルの一覧）を読み、レビューが要るかを決める。コード（`*.py`、`*.sh` など）か flow 定義（`flow.toml`）の変更があれば `review`、ドキュメントやバックログだけなら `skip`。コマンドが実行されなかったと表示された場合は、`git status --porcelain` を自分で実行する。
  - `review` を足す。プロンプトの内容（英語）:
    - 該当するレビューを実行し、指摘を一覧にする（ツール、`file:line`、指摘）。直さず、採否も決めない（do not decide）。コードの変更は `code-review` と `simplify`、`flow.toml` の変更は `deskil:flow-review`。スキルが使えなければ、同じ観点で自分でレビューする。
    - choices: `security`（when: 変更がシェルの実行・外部入力・ファイルパス・認証と権限・依存関係に触れる）→ `security_review`、`no_security`（when: 触れない）→ `triage`。
  - `security_review` を足す。`choices` は付けず、`goto = "triage"` だけにする。プロンプトの内容（英語）: `security-review` を実行し、指摘だけを `review` の一覧に足す。その報告はこのステップの終わりではない（not the end）。報告の形式や結びの文言には従わない。質問しない（do not ask）。報告を受けたら、一覧に足してすぐ `next` コマンドを実行する。
  - `triage` を足す。プロンプトの内容（英語）: 一覧の指摘ごとに採否を決める。採用は、実在する問題で、この項目の範囲内にあり、具体的な失敗の例が示せるもの。範囲外（out of scope）、誤検知、好みの問題は却下する。採用したものを今回だけ（once）直し、2 周目のレビューはしない。却下した指摘は、場所、指摘、理由を覚えておく（次の状態で記録する）。choices: `fixed`（when: 1 つ以上直した）→ `verify`、`not_fixed`（when: 何も直さなかった）→ `record_rejected`。
  - `record_rejected` を足す。プロンプトの内容（英語）: 却下した指摘があれば `docs/REVIEW-REJECTED.md` に追記する。却下がなければ nothing to do で、ファイルに触れない。ファイルがなければ、見出しと書式の説明（日本語）つきで作る。1 件ごとに、項目 ID、レビューの種類、場所、指摘、却下の理由を書く（日本語）。追記したら、独立した commit にする（バックログの commit や実装の commit とは混ぜない）。`goto = "commit"`。

- [ ] **Step 4: テストが通ることを確認する**

  Run: `uv run --with pytest pytest tests -q`
  Expected: すべて PASS。

  Run: `uv run plugins/deskil-dev/scripts/flow.py lint plugins/deskil-dev/skills/impl/flow.toml`
  Expected: エラーも警告もない。

- [ ] **Step 5: `deskil:flow-review` の観点で確認する**

  Run: `uv run plugins/deskil-dev/scripts/flow.py dry-run plugins/deskil-dev/skills/impl/flow.toml --results found,pass,review,fixed,pass`
  Expected: `review` が 1 回だけ出る。各プロンプトが単体で読め、`when` が明確。

- [ ] **Step 6: lint とコミット**

  Run: `uv run --with ruff ruff check .`
  Expected: エラーなし。

  ```bash
  git add plugins/deskil-dev/skills/impl/flow.toml tests/test_deskil_dev_plugin.py
  git commit -m "impl: review the change once before committing and record rejected findings"
  ```

---

### Task 2: ドキュメントとバックログ

**Files:**
- Modify: `docs/BACKLOG.md`、`README.md`（`deskil-dev` の説明があれば）
- Create: なし（`docs/REVIEW-REJECTED.md` は、最初の却下が出たときに `impl` が作る）

- [ ] **Step 1: バックログに項目を足す（`deskil-dev:add` の手順）**
  - `backlog.py next-id` で ID を取る。
  - 項目（日本語、`todo`、P2）: 「却下したレビュー指摘の棚卸し」。背景: `impl` のレビューで却下した指摘は `docs/REVIEW-REJECTED.md` に溜まる。概要: 溜まった記録を読み、有効なものを `deskil-dev:add` でバックログに積み、処理済みの記録を片付けるスキルを足す。未決: 記録の処理済みの印、棚卸しを起動する目安。
  - 設計書の「非ゴール」の `B-NNN` を、取った ID に置き換える（`docs/superpowers/specs/2026-11-22-impl-review-design.md`）。

- [ ] **Step 2: README を確認する**
  - `README.md` に `impl` の流れの説明があれば、レビューの状態を 1 行足す（英語）。なければ変更しない。

- [ ] **Step 3: 検証とコミット**

  Run: `uv run plugins/deskil-dev/scripts/backlog.py lint`、`uv run --with pytest pytest tests -q`
  Expected: lint は出力なし、テストは PASS。

  ```bash
  git add docs README.md
  git commit -m "docs: add the backlog item for triaging rejected review findings"
  ```

---

## 自己レビュー

- 設計書の対応: `impl` の flow の変更（`classify` / `review` / `security_review` / `triage` / `record_rejected`、1 周のみ、`security-review` で止まらない工夫）は Task 1、棚卸しのバックログ項目と設計書の ID は Task 2。
- 「1 周のみ」は `max_visits` と `on_exceed` で表し、テストで確かめる。
- 名前の整合: 状態名と choice のラベル（`review` / `skip` / `security` / `no_security` / `fixed` / `not_fixed`）は Task 1 の Interfaces とテストで同じ。
