# フローエンジンの配布方法の変更（`deskil` コマンド化）設計書

日付: 2026-11-23 / 状態: 承認待ち

## 1. 目的と背景

現状、`flow.py` は skill に **symlink またはコピー**で同梱している（[flow-engine-design.md](2026-11-22-flow-engine-design.md) §3、`README.md`）。

- このリポジトリの中では symlink で足りる。`plugins/*/scripts/flow.py` が `shared/flow/flow.py` を指す。
- 他のリポジトリの `.claude/skills/` に skill を置くと、`flow.py` を持ち込む手段がコピーしかない。実際に、既存の skill を移行した利用者は、コピーと「更新があれば同期する task」で運用している。
- そのため、エンジンを直すたびに、**使っているリポジトリの数だけ PR が要る**。これが手間になっている。
- `${CLAUDE_PLUGIN_ROOT}` はプラグインの境界を越えられない。`deskil` プラグインが持つ `flow.py` を、別のプラグインや repo の skill から呼ぶこともできない。

エンジンを**リポジトリにコピーするもの**から、**マシンに導入するコマンド**へ変える。コマンドは `deskil` とし、エンジンは `deskil flow …` として呼ぶ。skill は `deskil flow …` を呼ぶだけにし、エンジンの更新は各リポジトリの PR を要しないようにする。

コマンド名を `deskil-flow` ではなく `deskil` に束ねるのは、コマンド名が skill の呼び出し・`allowed-tools`・更新の案内に入るため、あとから変えると利用者の skill も書き換えになるからである。

## 2. ゴール / 非ゴール / アンチゴール

### ゴール

1. `deskil` コマンドを、`uv tool install` で導入できる。更新は `uv tool upgrade deskil` だけで済む。
2. エンジンは `deskil flow <サブコマンド> …` で呼ぶ。既存の `flow.py` のサブコマンド（`start` / `next` / `lint` など）と引数は変えない。
3. skill 側は `flow.py` のコピーも symlink も持たない。
4. コマンドが無い環境では、skill が導入方法を案内して止まる（黙って失敗しない）。
5. `flow.toml` に必要なエンジンの最小版を書ける。古いエンジンは、定義を誤解釈せずに止まり、更新方法を案内する。
6. このリポジトリの `deskil` / `deskil-dev` / `feature-a` プラグインも、同じ呼び方に移る。これで `plugins/*/scripts/flow.py` の symlink がすべて無くなる。`deskil-dev` は `backlog.py` だけ、これまでどおり symlink で使う。
7. 将来、別の道具（バックログ管理など）を `deskil <名前> …` として足せる入口にする（足すのは今回ではない）。

### 非ゴール（今回はやらない。詳細は `docs/BACKLOG.md`）

- `backlog.py` と `deskil-dev` の配布、`deskil backlog …` の追加（B-066）。`deskil-dev` はこのリポジトリ専用で、`backlog.py` は相対 symlink のまま使う。
- PyPI への公開と、版を固定した実行（B-067）。今回は git からの導入に限る。
- Windows 対応（B-004）。`uv tool` 自体は動くが、検証しない。

### アンチゴール

- 導入していないマシンで、skill が原因の分かりにくいエラー（`command not found` だけ）で終わる。
- エンジンが古いのに、新しい書式の `flow.toml` を黙って動かし、誤った手順を出す。
- 導入の手間が、コピーの手間より増える。
- 入口を作るために、`flow.py` の CLI の中身を作り替える（今回は呼び方を包むだけにする）。

## 3. 制約

- エンジンは**単一ファイル・標準ライブラリのみ**を保つ（`shared/flow/flow.py`）。配布のために分割しない。
- 導入の前提は `uv` のみ。
- 実行時のネットワークは使わない（導入と更新のときだけ）。
- `README.md` とソースのコメント・メッセージは英語、`docs/` は日本語（プロジェクトの規則）。

## 4. 検討した案

| 案 | 内容 | 結果 |
|---|---|---|
| A | `uvx --from git+…@v1 flow …` を skill に書き、実行のたびに git から取る | 採用しない。実行にネットワークが要り、`allowed-tools` の書式が長くなる。移動タグは再現性も下げる |
| **B** | `uv tool install` で各マシンに入れ、skill はコマンドを呼ぶ | **採用**（利用者が選択） |
| C | コピー方式のまま、同期 task を共通化する | 採用しない。PR が各リポジトリに要る点が変わらない |

B の代償は、各マシンや CI で導入が要ること、マシンごとに版が違い得ることである。前者は §5.3 の案内、後者は §5.4 の最小版チェックで受ける。

コマンド名は、`deskil-flow`（`flow.py` だけの名前）か `deskil`（サブコマンドで束ねる）かで、利用者が `deskil` を選んだ。

## 5. 設計

### 5.1 パッケージ化とエントリポイント

- リポジトリのルートに `pyproject.toml` を置く。プロジェクト名は `deskil`、エントリポイントは `deskil = deskil:main`。
- 新しい小さなモジュール `deskil.py` を置く。役目は、第 1 引数でサブコマンドを選び、残りの引数を渡すことだけ。今回の対応は `flow` → `flow.py` の `main`。
  - `deskil flow start x.toml` は、これまでの `flow.py start x.toml` と同じ結果・同じ終了コードになる。
  - サブコマンドを省略した場合と、未知のサブコマンドは、使い方（対応するサブコマンドの一覧）を出して非 0 で終わる。
  - 将来の追加（B-066）は、対応表に 1 行足すだけで済む形にする。
- `flow.py` は `shared/flow/flow.py` のまま動かさない。`flow.py` のコマンドライン処理の内部（`argparse` の `prog` など）は、ヘルプの表示が `deskil flow …` になる範囲だけ直す。
- 版は `deskil.py`（または `flow.py`）の `__version__` を唯一の出どころにし、`deskil --version` で出す。`pyproject.toml` はそれを動的に読む。どちらに置くかは実装者が決める（§7）。
- 同梱するもの: `deskil.py`、`flow.py`、`flow.schema.json`（エディタ用スキーマ。`SCHEMA_FILE` がエンジンと同じディレクトリを見るため、導入後も解決できること）。
- 導入: `uv tool install git+https://github.com/wtnb75/deskil`
- 更新: `uv tool upgrade deskil`

### 5.2 skill の呼び方

| 現在 | 変更後 |
|---|---|
| `uv run ${CLAUDE_PLUGIN_ROOT}/scripts/flow.py start …` | `deskil flow start …` |
| `allowed-tools: Bash(uv run ${CLAUDE_PLUGIN_ROOT}/scripts/flow.py:*)` | `allowed-tools: Bash(deskil flow:*)` |
| `plugins/*/scripts/flow.py`（symlink） | 削除 |

- 対象: `plugins/deskil`、`plugins/feature-a`、`plugins/deskil-dev` の `flow.py` の symlink と、それを呼ぶ skill（`flow-author`、`flow-convert`、`flow-export`、`flow-review`、`review-loop`、`deskil-dev` の `run = [...]` を含む定義）。
- skill の本文と定義の書き換えは、呼び出し行だけでなく、次も含む（実装者は `rg 'flow\.py|symlink' plugins/` で取りこぼしを確かめる）。
  - `plugins/deskil/skills/flow-convert/flow.toml` と `flow-export/flow.toml`: notes の「`flow.py <args>` は `uv run …/flow.py <args>` のこと」と、各ステートの `flow.py lint` / `fmt` / `dry-run` / `export` / `graph` の文を `deskil flow …` にする。
  - `flow-export` の手順（`allowed-tools` から `flow.py` を外す、同梱の symlink を外す）は、`Bash(deskil flow:*)` を外す手順に直し、symlink の話は削除する。
  - `flow-author` の「skill に組み込むとき」（`allowed-tools` を足し、相対 symlink で同梱する）と、`flow-convert/flow.toml` の同じ趣旨の文は、`deskil flow` を呼び、先頭に §5.3 の導入確認を置く、に直す。
  - `deskil-dev` の `add` / `decide` / `prio` / `impl` の `flow.toml` の notes にある「`backlog.py` and `flow.py` still find the backlog…」の文は、`backlog.py` と `deskil flow` に直す。
- このリポジトリ自身を開発する人は、導入済みの `deskil` ではなく作業ツリーのエンジンを使いたい。`README.md` の開発の節に、`uv tool install --editable .` で導入する手順を書く（`deskil-dev` の skill が、編集中の `flow.py` で動く）。
- `Taskfile.yml` の `lint-flow` は `uv run shared/flow/flow.py lint` のままでよい（このリポジトリの開発用なので、コミット前のソースを直接使う）。
- `backlog.py` と `common.sh` の symlink は変えない。`CLAUDE.md` の「共有スクリプト」の記述から、`flow.py` を外す。
- `flow.toml` の `run = ["uv", "run", "${DEF_DIR}/…"]` のような、定義内のコマンドは対象外（エンジンの呼び出しではない）。
- README の `uv run flow.py …` の一覧は `deskil flow …` に直す。

### 5.3 コマンドが無いときの案内

- `flow-author`、`flow-convert` など、`deskil` を使う skill の最初の手順に、次の確認を置く:
  `deskil --version` を実行し、`command not found` なら、次を伝えて**止まる**。

  > `deskil` が見つかりません。`uv tool install git+https://github.com/wtnb75/deskil` で導入してください。

- この確認と案内文は、`flow-convert` が生成する skill の雛形と、`flow-author` の「skill に組み込むとき」の手順（現在は symlink を勧めている）に入れる。移行する skill が各自で書かなくて済むようにする。
- `uv` 自体が無い場合の案内は書かない（`uv` の導入手順は、このプロジェクトの範囲外）。

### 5.4 エンジンの最小版チェック

- `flow.toml` のトップレベルに、任意のキー `engine` を足す。値は `deskil` の版の条件の文字列。
  例: `engine = ">=1.4"`
- 書式は、比較演算子（`>=` のみ対応）と版（`MAJOR.MINOR[.PATCH]`）。ほかは `lint` がエラーにする。範囲指定（`<`、`,`）は今回は扱わない。
- `start` / `lint` / `dry-run` / `export` など、定義を読むコマンドは、読み込みの最初に `engine` を検査する。満たさなければ、次を出して**終了コード非 0 で止まる**:

  > この定義は deskil 1.4 以上が必要です（導入済み: 1.2）。`uv tool upgrade deskil` で更新してください。

- 既存の `schema = 1`（定義の書式の版）とは別物。`schema` は書式が互換でなくなるときだけ上げ、`engine` は機能の追加で上げる。
- `TOP_KEYS` に `engine` を足す。`flow.schema.json` と `flow new` の雛形（コメントで説明）も更新する。
- `engine` が無い定義は、版を問わず動く（既存の定義を壊さない）。
- `include` された部品の `engine` の扱いは §7。
- 初版の版は `1.0.0`。このリポジトリの既存の定義には `engine` を足さない。

### 5.5 移行（利用者向け）

README に次を書く。

1. `uv tool install git+https://github.com/wtnb75/deskil`
2. skill の `flow.py` のコピーと同期 task を削除する。
3. skill の呼び出しを `deskil flow …` に、`allowed-tools` を `Bash(deskil flow:*)` に書き換える。

## 6. テスト

- `deskil --version` が版を出す。サブコマンドなし・未知のサブコマンドは、使い方を出して非 0 で終わる。
- `deskil flow <サブコマンド> …` が、`flow.py <サブコマンド> …` と同じ出力・終了コードになる（代表として `lint`、`start` / `next`、`export`）。
- `engine` の検査: 満たす／満たさない／書式不正／`engine` なし、のそれぞれで終了コードとメッセージを確かめる。
- `pyproject.toml` から導入できる（`uv tool install` を一時ディレクトリで実行し、`deskil flow lint` が動く。`flow.schema.json` が見つかる）。
- 既存のテストは、`flow.py` を直接呼ぶ形のまま通る。
- `plugins/*/scripts/flow.py` が無くなったあと、`task lint-flow` と各 skill の `allowed-tools` が一致している（grep で `scripts/flow.py` が残っていない）。

## 7. 実装者に任せること・未決

- ビルドのバックエンド（setuptools か hatchling か）と、`__version__` の置き場所・動的な読み方。
- `include` された部品の `engine`（§5.4）。部品が親より新しい版を要求するのは稀なので、迷うなら「親だけが持てる（部品に書いたら lint エラー）」にしてよい。
- `flow.py` の `argparse` の `prog` を、直接実行のときと `deskil flow` 経由のときで切り替える方法。
- `uv tool install` を CI で使うときの手順は、需要が出てから書く。

## 8. 完了条件

- 別のリポジトリの `.claude/skills/` に、`flow.py` を置かずに `deskil flow …` で動く skill を置ける（実機で確認する）。
- コマンドが無いとき、skill が導入コマンドを案内して止まる。
- `engine` を満たさない定義が、更新方法つきのエラーで止まる。
- `plugins/*/scripts/flow.py` の symlink が無くなり、`task test` / `task lint` / `task lint-flow` が通る。
