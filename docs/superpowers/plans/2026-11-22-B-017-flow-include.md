# B-017 flow: include による定義の部品化 実装計画

B-017 の「判断」（include 方式）を実装する。run の仕組み（状態ファイル、`step_target`）は変えず、読み込み時に 1 枚の状態機械へ展開する。

## 書式

```toml
[states.test]
include = "parts/test.toml"
exits = { ok = "review", fail = "fix" }   # サブの終了ステートID = 親のステートID
```

- include ステートに書けるキーは `include` と `exits` のみ。`prompt` などは書かない（書くと lint エラー）。
- サブ定義は通常の定義と同じ書式（`schema = 1`、`start`、`notes`、`states`）。

## 展開の規則

- サブのステート `s` は `<親ステートID>__s` になる（入れ子は `a__b__c`）。展開後の ID が既存の ID や共通ノート名と衝突したら lint エラー（`id-collision`）。
- 親の include ステートへの遷移は、サブの `start` への遷移になる。サブの `start` が終了ステートなら lint エラー（`include-start-end`）。
- サブの内側から終了ステート `E` への遷移（`goto` / `choices` / `on_exceed`）は、`exits[E]` の親ステートへの遷移になる。サブの終了ステートは展開後に残さない。
- `exits` はサブの終了ステートをすべて網羅する（`exits-missing`）。サブにない終了 ID を書くとエラー（`exits-unknown`）。
- include の循環は lint エラー（`include-cycle`）。
- `notes.always` は、書かれた定義のステートにだけ付く。サブの `notes.common` の名前は `<親ステートID>__名前` に直し、サブのステートの `notes` も同じように直す。
- `max_visits` / `on_exceed` はサブの内部で閉じる（訪問回数は展開後の ID で数える）。
- パスは定義ファイルのあるディレクトリの内側に限る（字句的に判定。`..` と絶対パスは `include-outside`）。リンク先が外にある symlink は許す（共有の手段）。サブの `{ file = ... }`、`cwd`、`${DEF_DIR}` は、サブのファイルがあるディレクトリ基準。展開時に親の定義ディレクトリ基準へ書き直す（`${DEF_DIR}` は `${DEF_DIR}/<サブの相対ディレクトリ>` にする）。

## 実装（`shared/flow/flow.py`）

1. `read_toml` を「バイト列の読み込み」と「パース」に分け、読んだファイルのバイト列を記録できるようにする。
2. `lint_schema`: `STATE_KEYS` に `include` / `exits` を足し、include ステートの検査を `_check_state` に足す（`prompt` 不要、他のキー禁止、`exits` は表で値は存在するステート）。
3. `expand_includes(raw, path, read)`: 上の規則で展開した 1 枚の `raw` と lint の指摘を返す。サブのスキーマは `lint_schema` で検査し、指摘の `where` にサブのパスを付ける。展開後の各ステートに `_always`（そのステートに適用する `always`）を持たせる。
4. `lint_raw`: スキーマが通ったら展開し、展開後の `raw` に `lint_graph` をかける（到達不能・行き止まり・ループはサブをまたいで検査される）。
5. `load_definition`: 展開後の `raw` から `State` を作る。`State.always` を足し、`render_step` は `defn.always` でなく `st.always` を使う。`Definition` に `sources`（読んだファイルとバイト列）と `hash` を持たせる。
6. 定義のハッシュ（`run.definition_hash`）: include がなければ従来どおりルートファイルの sha256。あれば、ルートとすべての include ファイルを含めたハッシュにする。`next_step` は定義を読んでからハッシュを比べる。
7. `_ref_check`: `run` のコマンドが git の `ref` の内容と一致するかの検査を、ルートだけでなくすべての include ファイルに広げる。各ファイルの実体（symlink は解決した先のファイルのディレクトリで `git -C … show ref:./名前`）の内容と、読み込み時に記録したバイト列を比べ、一つでも違う・リポジトリの外にある・読めないときは表示のみにする（例外にしない）。全部一致すれば、読み込んだ定義がコミット済みのバイト列そのものから作られているので、`run` / `cwd` は定義からそのまま使う（コミット済みの内容の再展開はしない）。
9. symlink の規則: サブのスキーマは、サブの字句的な（解決前の）ディレクトリを基準に `lint_schema` で検査する。相対ディレクトリの接頭辞も字句的に計算する。展開後の値に `_check_text` を再実行しない。include パス自体は字句的に「定義ディレクトリの内側」を判定する（`{ file }` はリンクを解決してから判定するので、ここは意図的な違い。symlink での共有を成り立たせるため。設計書に明記する）。
10. 循環検出は、祖先のスタック（解決後のパス）で行う。同じ部品を 2 回（別の親、ひし形）include するのは正しい。
8. `graph` / `dry-run` は展開後の定義をそのまま使う（変更なし）。

## テスト（`tests/test_include.py` ほか）

- 展開: ID の付け方、入れ子、終了ステートの `exits` への置き換え（`goto` / `choices` / `on_exceed`）、`start` の include。
- lint: `exits-missing` / `exits-unknown` / `include-cycle` / `include-outside` / `include-missing` / `include-start-end` / `id-collision`、include ステートに他のキー、サブのスキーマ違反、サブをまたぐ到達不能。
- `notes`: `always` が親子で混ざらない、サブの `common` が名前空間を持つ。
- パス: サブの `{ file }`・`cwd`・`${DEF_DIR}` がサブ基準になる。symlink の include が使える。
- 実行: run が展開後の ID で進む。サブのファイルを書き換えると `definition changed` になる。サブの `run` は git の `ref` と一致するときだけ実行される（サブを書き換えた場合は表示のみ）。
- 既存の `test_load_reads_the_toml_once` は、読み込みの仕組みの変更に合わせて直す。

## ドキュメント

- `docs/superpowers/specs/2026-11-22-flow-engine-design.md` に include の節を足す。
- `plugins/deskil/skills/flow-author/SKILL.md`（と必要なら `flow-review` / `flow-convert`）に書式を足す。
- B-017 を `backlog.py` で `done` にする（PR を開いたあと）。

## 範囲外（バックログへ）

- 実行時のサブフロー（再帰）。
- `rename` が `exits` の値（親のステートID）を書き換えない。書き換えが必要な rename は lint エラーで拒否される（ファイルは変わらない）。
