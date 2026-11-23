# プロジェクトのルール

## 言語

- ソースコードのコメント、ログ、エラーメッセージ、`README.md` は英語で書く。
- 設計書、実装計画、バックログなど、`docs/` 配下のドキュメントは日本語で書く。

## 共有スクリプト

- `plugins/*/scripts/` 配下のスクリプト（`backlog.py`、`common.sh`）は、`shared/` 配下の実体へのシンボリックリンクである。
- スクリプトを編集するときは、リンクではなく実体（`shared/backlog/backlog.py`、`shared/scripts/common.sh`）を編集する。リンクへの書き込みは拒否される。
- `flow.py` は同梱せず、導入済みの `deskil` コマンド（`deskil flow …`）で呼ぶ。実体は `shared/flow/flow.py`。このリポジトリで `flow.py` を直すときは、`uv tool install --editable .` で作業ツリーのエンジンを使う。

## バックログ

- 初版では「やらない」と決めたアイデアや、後で確認する事項は、決めたその場で `docs/BACKLOG.md` に追記する。
- 書式と運用ルールは `docs/BACKLOG.md` の冒頭に従う。
- 設計書の「非ゴール」には、バックログの ID（`B-NNN`）を参照として書く。
- 突発的な修正や小さな実装は、バックログに載せずに直接実装してよい（`impl` を通さなくてよい）。バックログに載せるのは、見送った案や後で確認する事項だけにする。
- バックログを使わずにブランチを切るときも、先に `git fetch origin` をして、`origin/<デフォルトブランチ>` から切る（`git switch -c <name> origin/main --no-track`）。
