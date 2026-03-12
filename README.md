# 一様重み(等重み)による証明数え上げ

この実装は、命題 `phi` に対して「証明があるか」だけでなく、深さ制限付きで複数の証明木を列挙し、各証明を同じ重み `1` として扱います。

## 目的と定義

与えられた仮定集合 `Gamma` と目標 `phi` について、深さ上限 `d` の範囲で生成される証明木の個数を数えます。

\[
W_d(Gamma \vdash phi) = \left|\{T \mid T \text{ is a generated proof tree of } Gamma \vdash phi,\; depth(T) \le d\}\right|
\]

ここでの `depth(T)` は証明木の根から葉までの最大ノード数です。

注意:
- これは命題の真理確率ではありません。
- これは実装が生成する導出空間に対する「列挙ベースの証明数」です。

## 実行ガイド

前提:

- `proof-search.py` があるディレクトリで実行する。
- Python 3.10 以上を想定。

1. デモを実行する

```bash
python proof-search.py --demo
```

2. 単発クエリを実行する

```bash
python proof-search.py --assumptions "A -> B; A" --goal "B"
```

3. 否定と `False` を使う

```bash
python proof-search.py --assumptions "!A; A" --goal "False"
```

4. 重複除去モードを切り替える

```bash
python proof-search.py --assumptions "A; A" --goal "A" --dedup-mode standard
python proof-search.py --assumptions "A; A" --goal "A" --dedup-mode syntactic
python proof-search.py --assumptions "A; A" --goal "A" --dedup-mode structural
```

5. 探索の深さと表示件数を調整する

```bash
python proof-search.py --assumptions "A" --goal "A | B" --max-depth 7 --max-trees 2000 --top-k 20
```

6. 利用可能オプションを確認する

```bash
python proof-search.py --help
```

よく使う引数:

- `--assumptions`: 仮定列(`;`区切り)
- `--goal`: 目標命題
- `--max-depth`: 深さ上限
- `--max-trees`: 各状態で保持する証明木上限
- `--dedup-mode`: `standard | syntactic | structural`
- `--weight-mode`: `uniform | rule | length_penalty | combined`
- `--alpha`: 長さペナルティ係数 (`0 < alpha < 1`)
- `--rule-weight`: 規則重みの上書き (`rule=value`)
- `--enable-classical`: 古典規則（RAA）を有効化
- `--enable-derived-facts`: 中間命題 Δ を有効化
- `--max-derived-facts`: Δ のサイズ上限
- `--top-k`: 表示する証明木件数
- `--demo`: デモケース一括実行

## この実装で使っている推論規則

現在の探索器は次の規則だけを使います。

1. `assumption`
- 目標が仮定に一致すれば証明成功。
- 同じ式が仮定に複数回ある場合、各出現を別導出として数えます。

2. `and_left_assumption`, `and_right_assumption`
- 仮定に `A & B` があれば、`A` または `B` を取り出せる。

3. `intro_imp`
- 目標が `A -> B` のとき、仮定に `A` を追加して `B` を証明。

4. `split_and_goal`
- 目標が `A & B` のとき、`A` と `B` を両方証明。

5. `left_or_goal`, `right_or_goal`
- 目標が `A | B` のとき、左または右を証明。

6. `apply_imp_assumption`
- 仮定に `A -> B` があり目標が `B` なら、`A` の証明に還元。

7. `ex_falso_assumption`
- 仮定に `False` があれば、任意の目標を導出できる。

8. `intro_not`
- 目標が `!A` のとき、仮定に `A` を追加して `False` を導く。

9. `neg_elim_assumptions`
- 仮定に `!A` と `A` が同時にあれば `False` を導く。

10. `apply_not_assumption`
- 目標が `False` で仮定に `!A` があるとき、`A` の証明に還元。

11. `or_elim_assumption` (Phase 1追加)
- 仮定に `A | B` があり目標 `C` なら、2つの場合分析：
  - `A` を仮定に加えて `C` を証明
  - `B` を仮定に加えて `C` を証明
- この両方の証明パスから `C` を導出（case analysis）。

## 冗長証明の扱い

本実装は、冗長な導出をあえて保持します。

- 例: `A; A |- A` は `assumption #1` と `assumption #2` を別証明として数える。
- 以前のような証明木文字列ベースの重複除去は行いません。

そのため `Found proofs` は、論理的に同値な証明を潰した最小本数ではなく、探索規則上の分岐多重度を反映します。

重複除去モード `--dedup-mode`:

- `standard`: 現在の既定モード。重複除去しない(冗長証明を保持)。
- `syntactic`: 証明木の規則・状態表示・注釈・部分木順序が完全一致するものを同一視。
- `structural`: `syntactic` より粗い同一視。少なくとも仮定出現番号(`assumption #i`)を無視し、部分木は順序非依存で比較。

前提:
- 本実装では `syntactic` で同一視される2つの証明木は、常に `structural` でも同一視されます。
- すなわち同値類として `syntactic` は `structural` に含まれる(または同じ)設計です。

## 深さ制限と探索制限

主要パラメータ:

- `--max-depth`: 再帰探索の上限。
効果: 深い回り道証明や長い導出は探索対象から外れる。
直感: 「深さ d 以下の証明だけ数える」という切り方。
- `--max-trees`: 各状態で保持する証明木数の上限。
- `--dedup-mode`: 証明木同一視のモード。
- `--top-k`: 出力する証明木の表示件数。

重要な制約:

- `max-trees` に達した場合、それ以上の導出は切り捨てられます。
- したがって出力される証明数は、上限に達したケースでは厳密値ではなく下限寄りの近似になります。（少なくともこれだけあるとはいえる）

## 入力記法

- 含意: `->`
- 連言: `&`
- 選言: `|`
- 否定: `!`
- 偽定数: `False`
- 括弧: `( ... )`
- 原子命題: `A`, `B`, `P1`, `goal_2` など
- 仮定列: `;` 区切り

例:

```bash
python proof-search.py --assumptions "A -> B; A" --goal "B"
```

```bash
python proof-search.py --assumptions "!A; A" --goal "False" --dedup-mode structural
```

## 出力項目

- `Found proofs`: 生成された証明木本数
- `Expanded states`: 探索で展開したゴール状態数 (各証明木で使用したコスト（推論適用数）の合計)
- `Depth bound`: 指定した深さ上限
- `Proof depth range`: 見つかった証明木の深さ最小/最大
- `Depth distribution`: 深さごとの証明本数

## 実行例

```bash
python proof-search.py --demo
```

```bash
python proof-search.py --assumptions "A; A" --goal "A" --max-depth 3
```

後者では通常 `Found proofs: 2` となり、冗長導出を別カウントしていることを確認できます。

## 今後の拡張候補（多段階実装計画）

### Phase 1: 完了 ✓

- `or_elim_assumption`: 選言消去（∨ elimination）を実装。
- 自然演繹体系の対称性を回復（各結合子に introduction/elimination ペア）。

### Phase 2: Weighting Mode （完了 ✓）

- `--weight-mode {uniform, rule, length_penalty, combined}` の導入。
- 証明木に重み付けスコアリング：
  - `uniform`: w(T) = 1 （現在の挙動）
  - `rule`: 各推論規則に信頼度重み
  - `length_penalty`: 証明長によるペナルティ α^|T|
  - `combined`: 規則重み × 長さペナルティ

例:

```bash
python proof-search.py --assumptions "A -> B; A" --goal "B" --weight-mode rule
python proof-search.py --assumptions "A -> B; A" --goal "B" --weight-mode combined --alpha 0.9
python proof-search.py --assumptions "A -> B; A" --goal "B" --weight-mode rule --rule-weight intro_imp=0.8,assumption=0.9
```

### Phase 3: 証明長ペナルティ （完了 ✓）

- `--alpha <float>` でペナルティ係数を指定
- 冗長証明の抑制、探索爆発の緩和

実装方針（Phase 2と統合して一貫性優先）:

- `|T|` は証明木の推論ステップ数として定義
- `length_penalty`: `w(T) = alpha^|T|`
- `combined`: `w(T) = (∏ rule_weight) × alpha^|T|`

例:

```bash
python proof-search.py --assumptions "A -> B; A" --goal "B" --weight-mode length_penalty --alpha 0.9
python proof-search.py --assumptions "A -> B; A" --goal "B" --weight-mode combined --alpha 0.9
```

### Phase 4: 古典論理規則 （完了 ✓）

- `--enable-classical` オプションで古典モード有効化
- `reductio_ad_absurdum`: Γ ∪ {¬A} ⊢ False から Γ ⊢ A

実装メモ:

- 規則名: `raa`
- backward search:
  - `goal = A`
  - `subgoal = Γ ∪ {!A} ⊢ False`

例（古典モードでのみ証明可能なケース）:

```bash
python proof-search.py --assumptions "!!A" --goal "A"
python proof-search.py --assumptions "!!A" --goal "A" --enable-classical
```

### Phase 5: 中間命題（Derived Facts）（完了 ✓）

- 証明済みの中間命題を再利用する拡張状態 (Γ, Δ, G)
- Δ（導出済事実）に上限とサイズ制御

実装メモ:

- 状態: `(Gamma, Delta, Goal)`
- `--enable-derived-facts` 指定時のみ Δ を構築して探索で利用
- 追加制約:
  - 同一命題の重複追加禁止
  - `--max-derived-facts` によるサイズ上限
  - 既存の深さ制限を維持

例:

```bash
python proof-search.py --assumptions "A -> B; B -> C; A" --goal "C" --enable-derived-facts
python proof-search.py --assumptions "!!A" --goal "A" --enable-classical --enable-derived-facts --max-derived-facts 8
```

### 参考

- 各フェーズは独立可能で、並行して機能追加を検討可能
- 重複除去モード `--dedup-mode` と重み付けモード `--weight-mode` は並存
- 拡張の都度、README と デモケースを更新予定

