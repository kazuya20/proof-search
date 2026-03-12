# proof-search プロジェクト実装ノート

## 概要

backward proof search を使った命題論理の証明木列挙システム。
Phase 1～5 まで段階的に拡張してきた実験環境。

## アーキテクチャ概観

### コア: 証明木列挙器 (ProofEnumerator)

- メモ化つき DFS で状態空間を探索
- memo: (Gamma, Delta, Goal, depth) -> ProofTree list
- seen: 現在のパス上のサイクル検出
- max_depth, max_trees で爆発を制限

### 状態表現

基本:
```
GoalState = (assumptions: Tuple[Formula], goal: Formula)
```

Phase 5 以降:
```
GoalState = (assumptions: Tuple[Formula], derived: Tuple[Formula], goal: Formula)
```

derived (Delta) は再利用可能な導出済み命題。

### 推論規則の配置

各規則は ProofEnumerator.enumerate() の中で逐次試行:

1. assumption + assumption/derived_fact 直接照合
2. conjunction elimination（And の部分抽出）
3. ex falso（False からの自由な導出）
4. implication introduction（→ 導入）
5. conjunction introduction（∧ introduction）
6. disjunction introduction（∨ 導入）
7. disjunction elimination（case analysis）
8. implication elimination（→ 除去）
9. negation introduction（¬ 導入）
10. contradiction detection（¬, A から False）
11. negated assumption application
12. RAA（古典規則、enable_classical 時のみ）

各規則は add() で結果を results に追加。max_trees に達したら打ち切り。

## 各フェーズの機構

### Phase 1: 選言消去

**問題**: ∨ introduction は実装されても、∨ elimination が欠けていて、自然演繹体系の対称性が崩れていた。

**解決**: or_elim_assumption を追加
- 仮定に A | B があり、目標が C なら
- 2つのサブゴール：
  - (Gamma ∪ {A}) ⊢ C
  - (Gamma ∪ {B}) ⊢ C
- 両方の証明から C を導出（case analysis）

### Phase 2 + 3: 重み付けモデル

**問題**: 複数の証明が見つかるとき、どれを選ぶ？証明の「信頼度」や「効率性」をどう評価する？

**解決**: 重みスコア w(T) で証明木を順序付け

ProofTree ごとに:
```
w(T) = f(rule_weights, length_penalty, mode)
```

weight_mode の実装:
- uniform: 常に 1.0
- rule: 各規則の重みの積
- length_penalty: alpha^|T|（|T| = ステップ数）
- combined: 規則重み積 × alpha^|T|

DEFAULT_RULE_WEIGHTS の値は実験的調整待ち（assumption=0.95, intro_imp=0.75 など）。

### Phase 4: 古典規則

**問題**: 直観主義論理では !!A -> A が導出できない。古典モードを導入したい。

**解決**: RAA (reductio ad absurdum) を追加（enable_classical 時のみ）

```
Gamma, !A ⊢ False
―――――――――――――
Gamma ⊢ A
```

backward search では：
- 目標 = A（False でない）
- neg_goal = !A を追加した仮定で False を導く subgoal を探索
- 見つかったら raa ステップで纏める

raa の weight を 0.60 に設定（あえて低め）。

### Phase 5: Derived Facts (Delta)

**問題**: 長い含意列 A -> B -> C -> ... -> Z で、B を何度も再証明するのが無駄。中間結果を再利用したい。

**解決**: Delta を探索中に段階的に構築

```
State = (Gamma, Delta, Goal)
```

build_derived_facts():
- Gamma と Goal に出現する「候補フォーミュラ」を集める（subformula collection）
- 各候補について「現在の Gamma と Delta で証明可能か」を試す
- 証明できたら Delta に追加
- 固定点に達するまで反復（またはサイズ上限に達する）

制御:
- max_derived_facts: Delta のサイズ上限
- 反復の中での各候補試行は、bounded search (max_depth/max_trees 落とし）で高速化
- 同一命題の重複追加は自動防止

注意: 現在の実装では、Delta 構築時に使う bounded search の max_trees を min(32, max_trees) に落としている（爆発防止）。

## 探索制御

### depth の意味

- depth は再帰の深さ（GoalState を展開する深さ）
- depth > max_depth なら打ち切り
- proof tree の depth() メソッドはノード数（別物）

### step_count の意味

- 推論ステップ数：ProofTree のノード数
- 長さペナルティで使う |T| = step_count

### max_trees

- 各 (Gamma, Delta, Goal, depth) ごとに最大 max_trees 通りの証明を保持
- 超えたら後は切り捨て
- そのため "Found proofs" は下限寄りの近似値になる可能性

## 重複除去 (dedup_mode)

- standard: しない（冗長証明を保持）
- syntactic: 証明木の構造・規則・注釈が完全一致なら同一視
- structural: syntactic より粗い（assumption #i を無視、部分木は順序非依存）

## 出力フォーマット

### メタデータ行

```
Assumptions        : ...
Goal               : ...
Found proofs       : N
Expanded states    : M
Depth bound        : d
Dedup mode         : {standard,syntactic,structural}
Classical mode     : {True,False}
Derived facts mode : {True,False}
[Delta size limit  : N]
[Derived facts used: M]
Weight mode        : {uniform,rule,length_penalty,combined}
[Alpha             : 0.9X]
[Length definition : |T| = number of inference steps]
Proof depth range  : min..max
Proof length range : min_steps..max_steps
Total score        : sum(w)
Best score         : max(w)
```

### 分布

depth distribution / weight distribution（weight_mode != uniform のとき）

### 証明表示

```
[i] depth=D steps=S weight=W.XXXXXX
  - rule: state [note]
    - subrule: ...
```

## よくある落とし穴

### 1. メモ化キーの設計

GoalState.key() が重要：
```python
def key(self) -> Tuple[...]:
    return (
        tuple(sorted(assumptions, key=str)),  # 順序を正規化
        tuple(sorted(derived, key=str)),
        goal,
    )
```

仮定の順序を正規化しないと、同じ論理的状態でもキーが異なり、メモが効かない。

### 2. cycle detection

```python
active_key = (state.key(), depth)
if active_key in self.seen:
    return []  # 同じ深さで同じ状態に到達 = サイクル
```

ただし同じ状態でも *異なる深さ* では再帰してよい。

### 3. context_facts の使用

Phase 5 で Gamma と Delta の両方を統一的に扱うため、context_facts として:
```python
context_facts: List[Tuple[str, int, Formula]] = [
    ('assumption', id, formula),
    ('derived', id, formula),
]
```

これにより、conjunction elimination / implication elimination が自動的に Gamma と Delta の両方に適用される。

### 4. enable_classical の条件

```python
if self.enable_classical and not isinstance(goal, Bottom):
    # RAA を試す
```

goal = False なら RAA は不要（すでに他の規則で処理）。

## パフォーマンス考慮

### 爆発的な増殖の源

1. **選言**: A | B を目標にすると、left と right の 2 パターン分岐
2. **連言introduction**: left × right の全組み合わせ（直積）
3. **or_elim_assumption**: case analysis で 2 × 2 = 4 分岐
4. **RAA**: goal ごとに !A + subgoal の新規展開

### 制限方法

- max_depth: 再帰深さで早期打ち切り
- max_trees: 状態ごとの証明数上限
- Bounded Delta search: build_derived_facts での max_trees 低下

## 実装単位

### Formula AST

Atom / And / Or / Imp / Bottom / Not

frozen dataclass で immutable 効かしている（hashable にするため）。

### Parser

TOKEN_RE で字句解析、再帰下降解析で構文解析。
- 右結合的な含意: A -> B -> C = A -> (B -> C)

### ProofTree + Step

ProofTree: ノード = Step + 子リスト
Step: (rule名, 状態表示, 注釈)

syntactic_key / structural_key で dedup 対応。

## 今後の検討事項

1. **Delta の最適化**
   - 現在は subformula collection なのでサイズが大きい
   - 候補を Goal の必要部分式に制限するなど

2. **rule weights の学習**
   - 現在は手調整
   - 成功確率などから自動調整できるか

3. **複数ゴール同時探索**
   - currently single goal
   - 複数ゴール AND / OR などが必要か

4. **逆参照情報の活用**
   - なぜ failed したか を記録して、似た状態でのカット

5. **並列探索**
   - 現在シングルスレッド
   - 異なる depth レベルを並列化できるか

## テスト・検証例

簡単な例:

```bash
python proof-search.py --assumptions "A" --goal "A"
# Found proofs: 1 (直接 assumption)
```

選言消去:

```bash
python proof-search.py --assumptions "A | B; A -> C; B -> C" --goal "C"
# Found proofs: 複数、or_elim_assumption を含む
```

古典:

```bash
python proof-search.py --assumptions "!!A" --goal "A" --enable-classical
# Found proofs: 複数、raa を含む
```

Derived Facts:

```bash
python proof-search.py --assumptions "A -> B; B -> C; A" --goal "C" --enable-derived-facts
# Found proofs: 3+、derived_fact を使うパスも出現
```

## Git / ファイル整理

### ファイル構成

```
proof-search/
  proof-search.py     # メイン実装
  README.md           # 利用者向けドキュメント
  note.md             # このファイル（内部ノート）
  output.txt          # 出力ログ（不要ならクリア）
```

### GitHub 公開について

- README.md: 公開（利用方法）
- proof-search.py: 公開（実装）
- note.md: 公開しない（内部メモ）
- output.txt: 公開しない（テスト出力）

`.gitignore` に note.md と output.txt を追加推奨。
