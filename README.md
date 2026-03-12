# Backward Proof Search Playground

このプロジェクトは、自然演繹ベースの backward proof search を使って、命題論理の証明木を列挙・比較するための実験環境です。

現在は以下を統合したシステムになっています。

- 直観主義的な基本規則群
- 選言消去（case analysis）
- 重み付きスコアリング（規則重み / 長さペナルティ / 統合）
- 古典規則（RAA）をオプションで有効化
- 中間命題 Delta（Derived Facts）の再利用

## 何をするツールか

与えられた仮定 Gamma と目標 phi に対して、深さ制限つきで証明木を列挙します。

- 充足判定だけでなく、複数の導出を保持
- 証明ごとに重みを計算して並べ替え可能
- 探索挙動を CLI オプションで切り替え可能

注意:

- ここでの score は真理確率ではなく、探索上の評価値です。
- 証明数は探索制限（max-depth, max-trees）に依存します。

## 状態モデル

基本状態:
s
- (Gamma, Goal)

Derived Facts 有効時:

- (Gamma, Delta, Goal)

Delta は、探索中に再利用する導出済み命題の集合です。

## 対応している推論規則

主な規則:

- assumption
- derived_fact
- and_left_assumption, and_right_assumption
- intro_imp, apply_imp_assumption
- split_and_goal
- left_or_goal, right_or_goal
- or_elim_assumption
- ex_falso_assumption
- intro_not, neg_elim_assumptions, apply_not_assumption
- raa（enable-classical 時のみ）

## 重みモデル

weight-mode:

- uniform
  - w(T) = 1
- rule
  - w(T) = product(rule_weight)
- length_penalty
  - w(T) = alpha^|T|
- combined
  - w(T) = product(rule_weight) * alpha^|T|

ここで |T| は証明木の推論ステップ数です。

制約:

- 0 < alpha < 1
- 0 < rule_weight <= 1

## 実行方法

前提:

- Python 3.10 以上
- proof-search.py があるディレクトリで実行

ヘルプ:

```bash
python proof-search.py --help
```

単発実行:

```bash
python proof-search.py --assumptions "A -> B; A" --goal "B"
```

デモ:

```bash
python proof-search.py --demo
```

## 主要オプション

- --assumptions
  - 仮定列（; 区切り）
- --goal
  - 目標命題
- --max-depth
  - 再帰探索上限
- --max-trees
  - 各状態で保持する証明木上限
- --top-k
  - 表示する証明木数
- --dedup-mode {standard, syntactic, structural}
  - 証明木の同一視レベル
- --weight-mode {uniform, rule, length_penalty, combined}
  - 重み計算方式
- --alpha
  - 長さペナルティ係数（length_penalty / combined で使用）
- --rule-weight
  - 規則重みの上書き（rule=value 形式）
- --enable-classical
  - 古典規則 raa を有効化
- --enable-derived-facts
  - Delta を有効化
- --max-derived-facts
  - Delta のサイズ上限
- --brief
  - 証明木の詳細表示を省略し、要約のみ表示

## よく使う例

1. 標準探索

```bash
python proof-search.py --assumptions "A -> B; A" --goal "B"
```

2. 選言消去（case analysis）

```bash
python proof-search.py --assumptions "A | B; A -> C; B -> C" --goal "C"
```

3. 重み付きランキング

```bash
python proof-search.py --assumptions "A -> B; A" --goal "B" --weight-mode rule
python proof-search.py --assumptions "A -> B; A" --goal "B" --weight-mode combined --alpha 0.9
```

4. 古典モード（RAA）

```bash
python proof-search.py --assumptions "!!A" --goal "A" --enable-classical
```

5. Derived Facts を使う

```bash
python proof-search.py --assumptions "A -> B; B -> C; A" --goal "C" --enable-derived-facts --max-derived-facts 8
```

6. 長い証明表示を抑える（brief）

```bash
python proof-search.py --assumptions "A | B; A -> C; B -> C" --goal "C" --max-depth 6 --top-k 5 --brief
```

## 出力の見方

- Found proofs
  - 見つかった証明木数
- Expanded states
  - 展開した状態数
- Classical mode / Derived facts mode
  - どの拡張が有効か
- Proof depth range / Proof length range
  - 証明の深さ・ステップ数分布
- Total score / Best score
  - 重みモデル下での集計値
