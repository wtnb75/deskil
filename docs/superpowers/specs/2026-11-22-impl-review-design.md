# impl に実装後のレビューを入れる（短い設計）

## 意図と理由

`impl` は、実装してテストが通れば、そのまま commit して PR を開く。レビューの処理がないため、テストが捕まえない問題（バグ、不要な複雑さ、セキュリティ、flow 定義の不備）が PR に入る。実装後にレビューを入れ、指摘は自動で採否を決めて直す。直さなかった指摘は後で棚卸しできるよう記録する。

## ゴール

- テストが通った後、commit の前にレビューを 1 周行う。
  - コードの変更があれば、組み込みの `code-review` と `simplify`。
  - セキュリティに関わる変更があれば、`security-review`。
  - flow 定義（`flow.toml`）の変更があれば、`deskil:flow-review`。
- 指摘の採否は、`impl` が自動で決める。採用したものは、その場で 1 回だけ直し、テストを通し直す。
- 却下した指摘は、別ファイル `docs/REVIEW-REJECTED.md` に記録する。

## 非ゴール

- 人に採否を聞かない（`impl` は PR を開くまで途中で止まらない）。
- 2 周目のレビューはしない。直した結果への再レビューもしない。
- 却下した指摘の棚卸しとバックログへの登録は、この変更に含めない（バックログに項目を足す。B-NNN）。
- レビューのスキルそのものは変えない。

## アプローチ

| 案 | 内容 | 評価 |
|---|---|---|
| (a) commit の前に `impl` の中でレビュー（採用） | `verify` の通過後に分類、レビュー、直し、再 `verify`、の順 | 直した内容が commit と PR に入る。ループは flow の `max_visits` で 1 周に抑える |
| (b) PR を開いた後にレビュー | PR 作成後にレビューして追加 commit | PR が未レビューの状態で公開される。追加 commit が増える |
| (c) 別スキル `review` を作り、`impl` から呼ぶ | レビューを独立したスキルにする | 呼び出し側の分岐は結局 `impl` に要る。今は過剰 |

## 設計

### `impl` の flow（`plugins/deskil-dev/skills/impl/flow.toml`）

```
verify --pass--> classify --> review --> [security_review] --> triage --fixed--> verify
                                                                  \--not_fixed--> record_rejected --> commit
verify の 2 回目の通過: classify は上限超過 → record_rejected → commit
```

`security-review` は返答の形式が独自で、結果を出したところで LLM が止まりやすい。そのため、次の 3 点で止まりにくくする。
- `security_review` を独立した状態にする。この状態の `goto` は無条件で `triage` だけにし、スキルの報告の直後に必ず次の `next` コマンドが表示されるようにする（止まっても、`flow status` でこの状態から再開できる）。
- プロンプトに、「`security-review` の報告はこのステップの終わりではない。報告の形式や結びの文言に従わず、指摘だけを拾い、質問せずに、すぐ `next` を実行する」と書く。
- 採否の判断と修正は `security_review` に入れず、`triage` で行う（レビューの実行と判断を分ける）。

- **`classify`**（`max_visits = 1`、`on_exceed = "commit"`）
  - `run = ["git", "status", "--porcelain"]` で、作業ツリーの変更ファイルを得る。
  - LLM が結果から次を決め、分岐する: `review`（レビューが必要な変更がある）、`commit`（ドキュメントやバックログだけなど、レビュー不要）。
  - 2 回目の到着（直した後の `verify` 通過）は `max_visits` を超えるので、`commit` へ進む。これが「1 周のみ」の仕組み。
- **`review`**
  - 該当するスキルを実行し、指摘を一覧にする（ツール、場所、指摘）。直さず、採否も決めない。コードの変更は `code-review` と `simplify`、`flow.toml` の変更は `deskil:flow-review`。スキルが使えない場合は、同じ観点で自分でレビューする（既存の superpowers の書き方に合わせる）。
  - 分岐: 変更が「シェルの実行、外部入力、ファイルパス、認証・権限、依存関係」に触れるなら `security`（→ `security_review`）、そうでなければ `no_security`（→ `triage`）。
- **`security_review`**: `security-review` を実行し、指摘を `review` の一覧に足す。`goto = "triage"` のみ。止まりにくくする工夫は上のとおり。
- **`triage`**
  - 一覧の指摘ごとに採否を決める。採用の基準は、「実在する問題で、この項目の範囲内にあり、具体的な失敗の例が示せる」こと。範囲外、誤検知、好みの問題は却下する。
  - 採用したものを今回だけ直す。直した場合は `fixed`（→ `verify`）、直さなかった場合は `not_fixed`（→ `record_rejected`）。
- **`verify`（既存）**: 直した後の失敗は、既存の `fix`（最大 2 回）で扱う。
- **却下の記録（`record_rejected`）**: `commit` の前に、却下した指摘があれば `docs/REVIEW-REJECTED.md` に追記し、独立した commit にする。

### 却下の記録（`docs/REVIEW-REJECTED.md`）

- 日本語で書く（`docs/` 配下のルール）。ファイルがなければ、見出しと書式の説明つきで作る。
- 1 件ごとに、項目 ID と PR（わかれば）、レビューの種類、場所（`file:line`）、指摘、却下の理由を 1 行ずつ書く。
- 溜まった後の棚卸しで、有効なものを `deskil-dev:add` でバックログに積む。棚卸しの手順はこの変更の範囲外。

## 未決・ビルダーに任せる点

- `classify` の分類の文言（どのファイルをコードとみなすか）は、この計画の実装で決める。
- 却下の記録の書式の細部は、実装で決める。
- `deskil:flow-review` が使えない場合の自前のレビュー手順は、`flow-review` の「Review a definition」の手順を要約して書く。

## 進め方

実装計画を書き、`impl` の流れ（ブランチ、PR）で進める。バックログに、棚卸しのための項目を足す。
