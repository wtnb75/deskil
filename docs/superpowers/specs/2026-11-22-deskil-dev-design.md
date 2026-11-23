# 開発用プラグイン（deskil-dev）設計書

## 目的

このリポジトリを開発していく流れ（思いつきを積む → 優先順位をつける → やり方を決める → 設計・実装して PR にする）を、スキルとして配布できるようにする。スキルは deskil 自身の flow エンジンで書く。

- 配布するプラグインにする理由: 実際に使いながら手順の欠点を見つけ、改善につなげやすくするため（自分たちで使う＝dogfooding）。
- 手順を flow 定義にする理由: 手順の飛ばしや暴走（修正の無限ループなど）を、`max_visits` などの上限で機械的に止めるため。

## ゴール

1. プラグイン `deskil-dev` を `plugins/deskil-dev/` に作り、`marketplace.json` に載せる。
2. バックログの各手順に対応する 4 つのスキル: `backlog-add` / `backlog-prioritize` / `backlog-decide` / `backlog-implement`。それぞれ `flow.toml` を持つ。
3. バックログの操作を機械的に行う小さな CLI `backlog.py`（標準ライブラリのみ、Python 3.11+）。ID の採番、一覧、書式検査など、LLM が間違えやすい部分を任せる。
4. バックログの書式を変更し（優先度・依存・完了記録）、既存項目を移行する。
5. B-009 / B-010 を `done` にする。

## 非ゴール

- 完了した項目の別ファイルへの分離（新規 B-022 として積む）。
- flow 定義へのコマンド実行の組み込み（B-013）。`backlog.py` は、LLM が手順の指示に従って呼ぶ。
- 人の承認ステップ（B-016）。承認が要る箇所は、手順文で「ユーザーに確認して待つ」と書く。
- flow の `start` への引数（B-018）。対象の項目は、会話から LLM が拾う。
- PR のマージ。スキルは PR を作るところまでで、マージはしない。

### 反目標（技術的にできても失敗とみなすもの）

- `backlog.py` が、利用者の文章（背景・概要など）を書き換える、または項目の並びを変える。
- `superpowers` が入っていないと動かない。
- スキルが、確認なしに main へ push する、または PR をマージする。

## 制約

- 配布するプラグインは、自分のディレクトリ内のファイルしか参照できない。`flow.py` と `backlog.py` は、相対 symlink で同梱する（既存の方針どおり）。
- コード・コメント・ログ・エラーメッセージ・README は英語、`docs/` 配下は日本語（`CLAUDE.md`）。スキルの手順文（`flow.toml`、`SKILL.md`）は、既存のスキルに合わせて英語とする。
- リポジトリ固有の規則（言語、テストコマンド、コミット規約）は、そのリポジトリの `CLAUDE.md` に従うよう、手順文で指示する。`task test` / `task lint` が Taskfile にあれば、それを使う。
- バックログの書式は、見出しと 1 行 1 項目の `- キー: 値` のみ。値は複数行にしない（`backlog.py` が構文解析できる範囲に収める）。

## 案の比較

| 案 | 内容 | 結果 |
|---|---|---|
| A（採用） | 手順ごとに 4 つのスキル。つなぎ役は BACKLOG の状態（`todo → ready → done`） | 「積むだけ」が軽い。flow が短く、1 スキル単位で直せる。B-009 / B-010 の分け方と一致 |
| B | 追加から PR までを 1 つの長い flow にする | 通しでは回せるが、積むだけのときに重く、定義が長くなる |
| C | 管理（add・prioritize）と開発（decide・implement）の 2 つに分ける | `decide` で止まる使い方の扱いが曖昧 |

## バックログの書式の変更

```
### B-NNN タイトル
- 状態: todo
- 優先度: P2             ← 追加。P1 / P2 / P3。todo / ready では必須、既定は P2
- 依存: B-009, B-011     ← 追加。任意
- 追加: YYYY-MM-DD
- 背景: ...
- 概要: ...
- 判断: ...
- 完了: YYYY-MM-DD       ← 追加。done のときだけ
- PR: #N                 ← 追加。done のときだけ（dropped には書かない）
```

- 並びは ID 順のまま。優先度は欄で表し、並べ替えた表示は `backlog.py list` が行う（状態 → 優先度 → ID。状態は `ready` を先）。
- 「ブロック中」: 依存先のどれかが `done` でない項目。`list` で印を付け、`backlog-implement` は選ばない。依存先が `dropped` の場合もブロック中とし、`list` が理由を示す（依存を見直す契機にする。**私の判断**）。
- `done` / `dropped` の置き場は、今までどおり `## done / dropped`。
- `docs/BACKLOG.md` の冒頭（運用ルールと書式）を更新する。

### 既存項目の移行

- 全項目に `優先度: P2` を付ける（本番の付け直しは、`backlog-prioritize` の初回実行で行う）。
- 依存を付ける: B-010 → B-009、B-012 → B-011、B-014 → B-011, B-012。B-018 は B-010 の前提としては付けない（B-010 は会話から項目を拾う形で先に作るため）。
- B-009 / B-010 は、実装後に `done`（完了日・PR 付き）にして `## done / dropped` へ移す。PR 番号は、PR を作ってから追記する別コミットで入れる（**私の判断**）。
- B-022「完了項目の別ファイル分離」を新規に積む。

## backlog.py

置き場所: `shared/backlog/backlog.py`（実行ビット付き）。`plugins/deskil-dev/scripts/backlog.py` から相対 symlink で同梱する。対象ファイルは、作業ディレクトリの `docs/BACKLOG.md`（`--file` で変更可）。

| サブコマンド | 動作 |
|---|---|
| `next-id` | 次の ID（`B-NNN`）を出す。最大の ID + 1（欠番は詰めない） |
| `list [--all] [--status s,...]` | 項目を「状態 → 優先度 → ID」の順に、短い表で出す。既定は `todo` / `ready` のみ。ブロック中に印を付ける |
| `show <ID>` | 1 項目だけを出す |
| `set <ID> <キー> <値>` | 1 行の欄（状態・優先度・依存・完了・PR）を書き換える。欄がなければ、決まった位置に足す |
| `archive <ID> --done\|--dropped [--pr N]` | 項目を `## done / dropped` へ移し、状態を更新する。`--done` は完了日（実行日）を書き、`--pr N` があれば PR も書く（PR は任意） |
| `lint` | 書式を検査し、問題を行番号付きで出す。問題があれば終了コード 1 |

`lint` の検査項目:

- ID の重複、見出しの書式、必須欄の欠落。
- 状態が 4 種のいずれか。優先度が P1〜P3（todo / ready は必須）。
- `ready` / `dropped` に `判断` があること。`done` に `完了` と `PR` があること。
- 置き場: `todo` / `ready` は上の節、`done` / `dropped` は下の節。
- 依存先が実在し、循環していないこと。

`add`（項目の追加）は、サブコマンドにしない。文章の本体は LLM が書くので、`next-id` で採番した ID で `Edit` により追記し、`lint` で確かめる。

## スキルと flow

どのスキルも、`SKILL.md` は既存の `review-loop` と同じ薄い作り（`flow.py start` を実行して従う）。`allowed-tools` に `flow.py` と `backlog.py` の実行を許可する。以下は状態の骨組みで、細部は実装者に任せる。

**backlog-add**: `check_dup`（`list --all` で重複を確認。重複なら既存項目の更新へ分岐）→ `write`（`next-id` で採番し、`todo` / `P2` で追記。初版で見送る理由を `背景` に書く）→ `lint`（失敗なら `fix`、`max_visits = 2`、超えたら `report_fail`）→ `report`。

**backlog-prioritize**: `survey`（`list` を読む）→ `propose`（優先度の案と理由を作る）→ `confirm`（ユーザーに見せて確認を待つ。修正があれば `propose` へ戻る）→ `apply`（`set` で書き換える）→ `lint` → `report`。

**backlog-decide**: `pick`（ユーザーの指定、なければブロック中でない先頭の `todo`）→ `investigate`（`show` と、関連するコードの確認）→ `options`（案を 2〜3 個出し、トレードオフと推奨を示す。`brainstorming` スキルがあれば使う）→ `confirm`（ユーザーが選ぶ）→ 結果で分岐: `ready`（`判断` を書き、`set` で `ready` に）／`dropped`（理由を書き `archive --dropped`）／`defer`（判断せず、分かったことを `概要` の未決に追記）→ `lint` → `report`。

**backlog-implement**: `pick`（ユーザーの指定、なければブロック中でない `ready` の優先度最上位。見つからなければ終了）→ `prepare`（作業ツリーがきれいか確認し、`git fetch origin` して、`origin/<デフォルトブランチ>` から `backlog/B-NNN-<slug>` のブランチを作る（B-026）。デフォルトブランチ名は `git symbolic-ref --short refs/remotes/origin/HEAD` で取り、取れなければ止めてユーザーに聞く。ローカルのデフォルトブランチは更新しない。worktree が使えれば使う）→ `plan`（小さな変更はその場で短く、大きければ計画書を `docs/superpowers/plans/` に。`writing-plans` があれば使う）→ `implement`（テストを先に書く方針。`test-driven-development` があれば使う）→ `verify`（テストと lint を実行。失敗なら `fix`、`max_visits = 2`、超えたら `report_fail` で PR を作らず終了）→ `finish_backlog`（`archive --done` で項目を移し、`lint`。PR 番号は書かない。commit はしない）→ `commit`（実装、バックログ、レビュー却下の記録を 1 コミットにまとめる。`CLAUDE.md` のコミット規約に従う）→ `open_pr`（push して `gh pr create`。マージはしない。PR のタイトルと本文は、`CLAUDE.md` が `docs/` の言語として定める言語で書く。規則がなければ日本語。コミットメッセージとコードのコメントは英語のまま。B-025）→ `back_to_default`（デフォルトブランチへ `git switch` する。pull もブランチの削除もしない。B-027）→ `report`。

## 受け入れ条件

- `uv run flow.py lint` が、4 つの `flow.toml` すべてで通る。
- `backlog.py` の各サブコマンドと `lint` の各検査に、テストがある（`tests/test_backlog.py`）。
- 実際の `docs/BACKLOG.md`（移行後）が `backlog.py lint` を通る。これもテストにする。
- プラグイン自体の検査（`plugin.json`、symlink が相対でリポジトリ内を指す、スキルの frontmatter）のテスト（`tests/test_deskil_dev_plugin.py`）がある。
- `task test` と `task lint` が通る。
- `README.md`（英語）に、`deskil-dev` を追記する。

## 実装者に任せること

- `flow.toml` の文面と状態名の細部、`list` の表の列と幅、`backlog.py` の引数の細部とエラーメッセージ。
- `lint` の行番号の数え方。
- `set` が欄を足すときの正確な位置（`状態` の直後、など）。
