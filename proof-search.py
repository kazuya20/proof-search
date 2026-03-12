from __future__ import annotations

import argparse
import re
import sys
import io
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Set, Dict, Literal

# Fix Windows Unicode encoding issue
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# ---------------------------
# Formula AST
# ---------------------------

class Formula:
    pass

@dataclass(frozen=True)
class Atom(Formula):
    name: str
    def __str__(self) -> str:
        return self.name

@dataclass(frozen=True)
class And(Formula):
    left: Formula
    right: Formula
    def __str__(self) -> str:
        return f"({self.left} & {self.right})"

@dataclass(frozen=True)
class Or(Formula):
    left: Formula
    right: Formula
    def __str__(self) -> str:
        return f"({self.left} | {self.right})"

@dataclass(frozen=True)
class Imp(Formula):
    left: Formula
    right: Formula
    def __str__(self) -> str:
        return f"({self.left} -> {self.right})"

@dataclass(frozen=True)
class Bottom(Formula):
    def __str__(self) -> str:
        return 'False'

@dataclass(frozen=True)
class Not(Formula):
    body: Formula
    def __str__(self) -> str:
        if isinstance(self.body, Atom):
            return f"!{self.body}"
        return f"!({self.body})"

# ---------------------------
# Parser
# ---------------------------

TOKEN_RE = re.compile(r"\s*(->|[()&|;!]|[A-Za-z][A-Za-z0-9_]*)")

class ParseError(ValueError):
    pass

class Parser:
    def __init__(self, text: str):
        self.tokens = [m.group(1) for m in TOKEN_RE.finditer(text)]
        reconstructed = ''.join(self.tokens)
        stripped = re.sub(r"\s+", "", text)
        if reconstructed != stripped:
            raise ParseError(f"Could not tokenize input near: {text}")
        self.i = 0

    def peek(self) -> Optional[str]:
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def eat(self, token: str) -> None:
        if self.peek() != token:
            raise ParseError(f"Expected {token!r}, got {self.peek()!r}")
        self.i += 1

    def parse_formula(self) -> Formula:
        return self.parse_imp()

    def parse_imp(self) -> Formula:
        left = self.parse_or()
        if self.peek() == '->':
            self.eat('->')
            right = self.parse_imp()  # right-associative
            return Imp(left, right)
        return left

    def parse_or(self) -> Formula:
        node = self.parse_and()
        while self.peek() == '|':
            self.eat('|')
            node = Or(node, self.parse_and())
        return node

    def parse_and(self) -> Formula:
        node = self.parse_not()
        while self.peek() == '&':
            self.eat('&')
            node = And(node, self.parse_not())
        return node

    def parse_not(self) -> Formula:
        if self.peek() == '!':
            self.eat('!')
            return Not(self.parse_not())
        return self.parse_atom()

    def parse_atom(self) -> Formula:
        tok = self.peek()
        if tok is None:
            raise ParseError("Unexpected end of input")
        if tok == '(':
            self.eat('(')
            node = self.parse_formula()
            self.eat(')')
            return node
        if tok == 'False':
            self.i += 1
            return Bottom()
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", tok):
            self.i += 1
            return Atom(tok)
        raise ParseError(f"Unexpected token: {tok}")


def parse_formula(text: str) -> Formula:
    p = Parser(text)
    node = p.parse_formula()
    if p.peek() is not None:
        raise ParseError(f"Unexpected trailing token: {p.peek()}")
    return node


def parse_assumptions(text: str) -> Tuple[Formula, ...]:
    text = text.strip()
    if not text:
        return tuple()
    parts = [part.strip() for part in text.split(';') if part.strip()]
    return tuple(parse_formula(part) for part in parts)

# ---------------------------
# Proof search objects
# ---------------------------

@dataclass(frozen=True)
class GoalState:
    assumptions: Tuple[Formula, ...]
    derived: Tuple[Formula, ...]
    goal: Formula

    def key(self) -> Tuple[Tuple[Formula, ...], Tuple[Formula, ...], Formula]:
        return (
            tuple(sorted(self.assumptions, key=str)),
            tuple(sorted(self.derived, key=str)),
            self.goal,
        )

    def pretty(self) -> str:
        asm = ', '.join(str(a) for a in self.assumptions) if self.assumptions else '∅'
        if self.derived:
            drv = ', '.join(str(d) for d in self.derived)
            return f"{asm} ; Δ={{{drv}}} ⊢ {self.goal}"
        return f"{asm} ⊢ {self.goal}"

@dataclass(frozen=True)
class Step:
    rule: str
    state_repr: str
    note: str

@dataclass
class ProofTree:
    step: Step
    subproofs: List['ProofTree'] = field(default_factory=list)

    def depth(self) -> int:
        if not self.subproofs:
            return 1
        return 1 + max(sp.depth() for sp in self.subproofs)

    def step_count(self) -> int:
        return 1 + sum(sp.step_count() for sp in self.subproofs)

    def lines(self, indent: int = 0) -> List[str]:
        prefix = '  ' * indent
        here = f"{prefix}- {self.step.rule}: {self.step.state_repr} [{self.step.note}]"
        acc = [here]
        for sp in self.subproofs:
            acc.extend(sp.lines(indent + 1))
        return acc

    def syntactic_key(self) -> Tuple[str, str, str, Tuple]:
        return (
            self.step.rule,
            self.step.state_repr,
            self.step.note,
            tuple(sp.syntactic_key() for sp in self.subproofs),
        )

    def structural_key(self) -> Tuple[str, str, str, Tuple]:
        note = self.step.note
        # Ignore assumption index to identify the same derivation shape.
        if self.step.rule == 'assumption':
            note = re.sub(r"^use assumption #\d+:\s*", '', note)
        child_keys = tuple(sorted((sp.structural_key() for sp in self.subproofs), key=str))
        return (self.step.rule, self.step.state_repr, note, child_keys)

# ---------------------------
# Proof enumerator
# ---------------------------

class ProofEnumerator:
    def __init__(
        self,
        max_depth: int = 6,
        max_trees: int = 1000,
        dedup_mode: Literal['standard', 'syntactic', 'structural'] = 'standard',
        enable_classical: bool = False,
    ):
        self.max_depth = max_depth
        self.max_trees = max_trees
        self.dedup_mode = dedup_mode
        self.enable_classical = enable_classical
        self.expanded = 0
        self.memo: Dict[Tuple[Tuple[Formula, ...], Tuple[Formula, ...], Formula, int], List[ProofTree]] = {}
        self.seen: Set[Tuple[Tuple[Tuple[Formula, ...], Tuple[Formula, ...], Formula], int]] = set()

    def _dedup(self, trees: List[ProofTree]) -> List[ProofTree]:
        if self.dedup_mode == 'standard':
            return trees[: self.max_trees]

        uniq: Dict[Tuple, ProofTree] = {}
        for t in trees:
            key = t.syntactic_key() if self.dedup_mode == 'syntactic' else t.structural_key()
            if key not in uniq:
                uniq[key] = t
            if len(uniq) >= self.max_trees:
                break
        return list(uniq.values())

    def enumerate(self, state: GoalState, depth: int = 0) -> List[ProofTree]:
        memo_key = (state.key()[0], state.key()[1], state.key()[2], depth)
        if memo_key in self.memo:
            return self.memo[memo_key]

        if depth > self.max_depth:
            self.memo[memo_key] = []
            return []

        # cycle check on same state at same depth along current path
        active_key = (state.key(), depth)
        if active_key in self.seen:
            return []

        self.seen.add(active_key)
        self.expanded += 1
        results: List[ProofTree] = []

        def add(tree: ProofTree):
            if len(results) < self.max_trees:
                results.append(tree)

        assumptions = list(state.assumptions)
        derived = list(state.derived)
        goal = state.goal
        state_repr = state.pretty()
        context_facts: List[Tuple[str, int, Formula]] = []
        for idx, f in enumerate(assumptions, 1):
            context_facts.append(('assumption', idx, f))
        for idx, f in enumerate(derived, 1):
            context_facts.append(('derived', idx, f))

        # 1. assumption
        # Count each matching assumption occurrence as a distinct derivation choice.
        for idx, asm in enumerate(assumptions, 1):
            if asm == goal:
                add(ProofTree(Step('assumption', state_repr, f'use assumption #{idx}: {goal}')))
        for idx, fact in enumerate(derived, 1):
            if fact == goal:
                add(ProofTree(Step('derived_fact', state_repr, f'use derived fact #{idx}: {goal}')))

        # 2. conjunction elimination from assumptions
        for src, idx, asm in context_facts:
            if isinstance(asm, And):
                if asm.left == goal:
                    add(ProofTree(Step('and_left_assumption', state_repr, f'use left side of {src} #{idx}: {asm}')))
                if asm.right == goal:
                    add(ProofTree(Step('and_right_assumption', state_repr, f'use right side of {src} #{idx}: {asm}')))

        # 2.5 ex falso from assumptions
        for src, idx, asm in context_facts:
            if isinstance(asm, Bottom):
                add(ProofTree(Step('ex_falso_assumption', state_repr, f'use contradiction {src} #{idx}: False')))

        # 3. implication introduction
        if isinstance(goal, Imp):
            substate = GoalState(state.assumptions + (goal.left,), state.derived, goal.right)
            subs = self.enumerate(substate, depth + 1)
            for sp in subs:
                add(ProofTree(Step('intro_imp', state_repr, f'assume {goal.left} and prove {goal.right}'), [sp]))

        # 4. conjunction introduction
        if isinstance(goal, And):
            left_state = GoalState(state.assumptions, state.derived, goal.left)
            right_state = GoalState(state.assumptions, state.derived, goal.right)
            lefts = self.enumerate(left_state, depth + 1)
            rights = self.enumerate(right_state, depth + 1)
            for lp in lefts:
                for rp in rights:
                    add(ProofTree(Step('split_and_goal', state_repr, f'prove both conjuncts of {goal}'), [lp, rp]))
                    if len(results) >= self.max_trees:
                        break
                if len(results) >= self.max_trees:
                    break

        # 5. disjunction introduction
        if isinstance(goal, Or):
            left_state = GoalState(state.assumptions, state.derived, goal.left)
            right_state = GoalState(state.assumptions, state.derived, goal.right)
            for sp in self.enumerate(left_state, depth + 1):
                add(ProofTree(Step('left_or_goal', state_repr, f'prove left side of {goal}'), [sp]))
            for sp in self.enumerate(right_state, depth + 1):
                add(ProofTree(Step('right_or_goal', state_repr, f'prove right side of {goal}'), [sp]))

        # 5.5 disjunction elimination from assumptions (case analysis)
        for src, idx, asm in context_facts:
            if isinstance(asm, Or):
                left_case = GoalState(state.assumptions + (asm.left,), state.derived, goal)
                right_case = GoalState(state.assumptions + (asm.right,), state.derived, goal)
                left_proofs = self.enumerate(left_case, depth + 1)
                right_proofs = self.enumerate(right_case, depth + 1)
                for lp in left_proofs:
                    for rp in right_proofs:
                        add(ProofTree(Step('or_elim_assumption', state_repr, f'case analysis on {src} #{idx}: {asm}; prove {goal} from both {asm.left} and {asm.right}'), [lp, rp]))
                        if len(results) >= self.max_trees:
                            break
                    if len(results) >= self.max_trees:
                        break

        # 6. implication elimination using assumptions
        for src, idx, asm in context_facts:
            if isinstance(asm, Imp) and asm.right == goal:
                substate = GoalState(state.assumptions, state.derived, asm.left)
                for sp in self.enumerate(substate, depth + 1):
                    add(ProofTree(Step('apply_imp_assumption', state_repr, f'use implication {src} #{idx}: {asm}; need {asm.left}'), [sp]))

        # 7. negation introduction
        if isinstance(goal, Not):
            substate = GoalState(state.assumptions + (goal.body,), state.derived, Bottom())
            for sp in self.enumerate(substate, depth + 1):
                add(ProofTree(Step('intro_not', state_repr, f'assume {goal.body} and derive False'), [sp]))

        # 7.5 classical reductio ad absurdum (optional)
        # Γ, ¬A ⊢ False  then Γ ⊢ A
        if self.enable_classical and not isinstance(goal, Bottom):
            neg_goal = Not(goal)
            substate = GoalState(state.assumptions + (neg_goal,), state.derived, Bottom())
            for sp in self.enumerate(substate, depth + 1):
                add(ProofTree(Step('raa', state_repr, f'classical: assume {neg_goal} and derive False'), [sp]))

        # 8. contradiction detection in assumptions for goal=False
        if isinstance(goal, Bottom):
            for src1, i, asm1 in context_facts:
                if isinstance(asm1, Not):
                    for src2, j, asm2 in context_facts:
                        if asm2 == asm1.body:
                            add(ProofTree(Step('neg_elim_assumptions', state_repr, f'use {src1} #{i} ({asm1}) and {src2} #{j} ({asm2})')))

        # 9. apply negated assumption to reduce goal=False to proving its body
        if isinstance(goal, Bottom):
            for src, idx, asm in context_facts:
                if isinstance(asm, Not):
                    substate = GoalState(state.assumptions, state.derived, asm.body)
                    for sp in self.enumerate(substate, depth + 1):
                        add(ProofTree(Step('apply_not_assumption', state_repr, f'use negated {src} #{idx}: {asm}; need {asm.body}'), [sp]))

        final = self._dedup(results)
        self.memo[memo_key] = final
        self.seen.remove(active_key)
        return final

# ---------------------------
# Reporting helpers
# ---------------------------

WeightMode = Literal['uniform', 'rule', 'length_penalty', 'combined']

DEFAULT_RULE_WEIGHTS: Dict[str, float] = {
    'assumption': 0.95,
    'intro_imp': 0.75,
    'split_and_goal': 0.78,
    'left_or_goal': 0.52,
    'right_or_goal': 0.52,
    'apply_imp_assumption': 0.62,
    'and_left_assumption': 0.90,
    'and_right_assumption': 0.90,
    'ex_falso_assumption': 0.40,
    'intro_not': 0.70,
    'neg_elim_assumptions': 0.80,
    'apply_not_assumption': 0.65,
    'or_elim_assumption': 0.68,
    'raa': 0.60,
    'derived_fact': 0.93,
}


def collect_subformulas(f: Formula) -> Set[Formula]:
    acc: Set[Formula] = {f}
    if isinstance(f, (And, Or, Imp)):
        acc |= collect_subformulas(f.left)
        acc |= collect_subformulas(f.right)
    elif isinstance(f, Not):
        acc |= collect_subformulas(f.body)
    return acc


def build_derived_facts(
    assumptions: Tuple[Formula, ...],
    goal: Formula,
    max_depth: int,
    max_trees: int,
    dedup_mode: Literal['standard', 'syntactic', 'structural'],
    enable_classical: bool,
    max_derived_facts: int,
) -> Tuple[Formula, ...]:
    if max_derived_facts <= 0:
        return tuple()

    candidates: Set[Formula] = set()
    for asm in assumptions:
        candidates |= collect_subformulas(asm)
    candidates |= collect_subformulas(goal)

    sorted_candidates = sorted(candidates, key=str)
    derived: List[Formula] = []

    # Iteratively enlarge Delta with provable formulas under bounded search.
    changed = True
    while changed and len(derived) < max_derived_facts:
        changed = False
        for cand in sorted_candidates:
            if cand in assumptions or cand in derived:
                continue
            enum = ProofEnumerator(
                max_depth=max_depth,
                max_trees=max(1, min(max_trees, 32)),
                dedup_mode=dedup_mode,
                enable_classical=enable_classical,
            )
            st = GoalState(assumptions, tuple(derived), cand)
            proofs = enum.enumerate(st)
            if proofs:
                derived.append(cand)
                changed = True
                if len(derived) >= max_derived_facts:
                    break

    return tuple(derived)


def parse_rule_weights(raw_items: List[str]) -> Dict[str, float]:
    weights = dict(DEFAULT_RULE_WEIGHTS)
    for item in raw_items:
        parts = [p.strip() for p in item.split(',') if p.strip()]
        for part in parts:
            if '=' not in part:
                raise ValueError(f'Invalid --rule-weight value: {part!r} (expected rule=value)')
            rule, value_text = [x.strip() for x in part.split('=', 1)]
            if not rule:
                raise ValueError(f'Invalid --rule-weight value: {part!r} (rule name is empty)')
            try:
                value = float(value_text)
            except ValueError as exc:
                raise ValueError(f'Invalid rule weight for {rule!r}: {value_text!r}') from exc
            if not (0.0 < value <= 1.0):
                raise ValueError(f'Rule weight for {rule!r} must satisfy 0 < w <= 1, got {value}')
            weights[rule] = value
    return weights


def _rule_weight_product(tree: ProofTree, rule_weights: Dict[str, float]) -> float:
    w = rule_weights.get(tree.step.rule, 1.0)
    for sp in tree.subproofs:
        w *= _rule_weight_product(sp, rule_weights)
    return w


def proof_length(tree: ProofTree) -> int:
    # |T| = number of inference steps in a proof tree.
    return tree.step_count()


def length_penalty(tree: ProofTree, alpha: float) -> float:
    return alpha ** proof_length(tree)


def proof_weight(tree: ProofTree, mode: WeightMode, rule_weights: Dict[str, float], alpha: float) -> float:
    if mode == 'uniform':
        return 1.0
    if mode == 'rule':
        return _rule_weight_product(tree, rule_weights)
    if mode == 'length_penalty':
        return length_penalty(tree, alpha)
    return _rule_weight_product(tree, rule_weights) * length_penalty(tree, alpha)


def summarize(
    assumptions: Tuple[Formula, ...],
    goal: Formula,
    max_depth: int,
    max_trees: int,
    top_k: int,
    dedup_mode: Literal['standard', 'syntactic', 'structural'],
    weight_mode: WeightMode,
    alpha: float,
    rule_weights: Dict[str, float],
    enable_classical: bool,
    enable_derived_facts: bool,
    max_derived_facts: int,
) -> str:
    derived: Tuple[Formula, ...] = tuple()
    if enable_derived_facts:
        derived = build_derived_facts(
            assumptions=assumptions,
            goal=goal,
            max_depth=max_depth,
            max_trees=max_trees,
            dedup_mode=dedup_mode,
            enable_classical=enable_classical,
            max_derived_facts=max_derived_facts,
        )

    state = GoalState(assumptions, derived, goal)
    enum = ProofEnumerator(
        max_depth=max_depth,
        max_trees=max_trees,
        dedup_mode=dedup_mode,
        enable_classical=enable_classical,
    )
    trees = enum.enumerate(state)
    weighted = [(t, proof_weight(t, weight_mode, rule_weights, alpha)) for t in trees]
    weighted.sort(key=lambda tw: (-tw[1], tw[0].depth(), '\n'.join(tw[0].lines())))
    trees = [t for t, _ in weighted]

    weight_hist: Dict[str, int] = {}
    for _, w in weighted:
        bucket = f'{w:.6f}'
        weight_hist[bucket] = weight_hist.get(bucket, 0) + 1

    depth_hist: Dict[int, int] = {}
    for t in trees:
        d = t.depth()
        depth_hist[d] = depth_hist.get(d, 0) + 1

    lines: List[str] = []
    lines.append('=' * 72)
    lines.append(f"Assumptions        : {'; '.join(str(a) for a in assumptions) if assumptions else '∅'}")
    lines.append(f"Goal               : {goal}")
    lines.append(f"Found proofs       : {len(trees)}")
    lines.append(f"Expanded states    : {enum.expanded}")
    lines.append(f"Depth bound        : {max_depth}")
    lines.append(f"Dedup mode         : {dedup_mode}")
    lines.append(f"Classical mode     : {enable_classical}")
    lines.append(f"Derived facts mode : {enable_derived_facts}")
    if enable_derived_facts:
        lines.append(f"Delta size limit   : {max_derived_facts}")
        lines.append(f"Derived facts used : {len(derived)}")
    lines.append(f"Weight mode        : {weight_mode}")
    if weight_mode in ('length_penalty', 'combined'):
        lines.append(f"Alpha              : {alpha}")
        lines.append('Length definition  : |T| = number of inference steps')
    if trees:
        min_depth = min(t.depth() for t in trees)
        max_proof_depth = max(t.depth() for t in trees)
        lines.append(f"Proof depth range  : {min_depth}..{max_proof_depth}")
        min_steps = min(t.step_count() for t in trees)
        max_steps = max(t.step_count() for t in trees)
        lines.append(f"Proof length range : {min_steps}..{max_steps}")
        lines.append(f"Total score        : {sum(w for _, w in weighted):.6f}")
        lines.append(f"Best score         : {weighted[0][1]:.6f}")
    lines.append('')
    if not trees:
        lines.append('No proof found within the current depth/size limits.')
        return '\n'.join(lines)

    lines.append('Depth distribution (proof_count by depth):')
    for depth in sorted(depth_hist):
        lines.append(f'- depth {depth}: {depth_hist[depth]}')
    lines.append('')
    if weight_mode != 'uniform':
        lines.append('Weight distribution (proof_count by weight):')
        for weight_text in sorted(weight_hist.keys(), key=lambda x: float(x), reverse=True):
            lines.append(f'- weight {weight_text}: {weight_hist[weight_text]}')
        lines.append('')
    lines.append(f'Showing {min(top_k, len(trees))} proof tree(s):')
    for i, (tree, w) in enumerate(weighted[:top_k], 1):
        lines.append(f"[{i}] depth={tree.depth()} steps={tree.step_count()} weight={w:.6f}")
        lines.extend(tree.lines(1))
        lines.append('')
    return '\n'.join(lines).rstrip()

# ---------------------------
# Demo and CLI
# ---------------------------

DEMO_CASES = [
    ("A; B", "A"),
    ("A; B", "A & B"),
    ("A & B", "A"),
    ("A -> B; A", "B"),
    ("False", "A"),
    ("!A; A", "False"),
    ("", "(!A -> !A)"),
    ("", "A -> A"),
    ("", "A -> (B -> A)"),
    ("A", "A | B"),
    ("", "(A & B) -> A"),
    ("A | B; A -> C; B -> C", "C"),
]


def run_demo(args: argparse.Namespace) -> None:
    for asm_text, goal_text in DEMO_CASES:
        assumptions = parse_assumptions(asm_text)
        goal = parse_formula(goal_text)
        print(summarize(
            assumptions,
            goal,
            args.max_depth,
            args.max_trees,
            args.top_k,
            args.dedup_mode,
            args.weight_mode,
            args.alpha,
            args.rule_weights,
            args.enable_classical,
            args.enable_derived_facts,
            args.max_derived_facts,
        ))


def main() -> None:
    ap = argparse.ArgumentParser(description='Enumerate multiple proofs with configurable weighting modes.')
    ap.add_argument('--assumptions', default='', help='Semicolon-separated assumptions, e.g. "A -> B; A"')
    ap.add_argument('--goal', help='Goal formula, e.g. "B" or "A -> (B -> A)"')
    ap.add_argument('--max-depth', type=int, default=6)
    ap.add_argument('--max-trees', type=int, default=1000)
    ap.add_argument('--top-k', type=int, default=10)
    ap.add_argument('--dedup-mode', choices=['standard', 'syntactic', 'structural'], default='standard')
    ap.add_argument('--weight-mode', choices=['uniform', 'rule', 'length_penalty', 'combined'], default='uniform')
    ap.add_argument('--alpha', type=float, default=0.90, help='Length penalty base for length_penalty/combined (0 < alpha < 1).')
    ap.add_argument('--enable-classical', action='store_true', help='Enable classical rule: reductio ad absurdum (RAA).')
    ap.add_argument('--enable-derived-facts', action='store_true', help='Enable derived facts Delta in search state: (Gamma, Delta, goal).')
    ap.add_argument('--max-derived-facts', type=int, default=16, help='Upper bound for Delta size when derived facts are enabled.')
    ap.add_argument(
        '--rule-weight',
        action='append',
        default=[],
        help='Override rule weights via rule=value (repeatable and comma-separated), e.g. --rule-weight intro_imp=0.8,assumption=0.9',
    )
    ap.add_argument('--demo', action='store_true')
    args = ap.parse_args()

    if not (0.0 < args.alpha < 1.0):
        print(f'Invalid --alpha={args.alpha}. Must satisfy 0 < alpha < 1.')
        return

    if args.max_derived_facts < 0:
        print(f'Invalid --max-derived-facts={args.max_derived_facts}. Must be >= 0.')
        return

    try:
        args.rule_weights = parse_rule_weights(args.rule_weight)
    except ValueError as e:
        print(f'Invalid --rule-weight: {e}')
        return

    if args.demo:
        run_demo(args)
        return

    if not args.goal:
        print('Provide --goal, or use --demo.')
        return

    assumptions = parse_assumptions(args.assumptions)
    goal = parse_formula(args.goal)
    print(summarize(
        assumptions,
        goal,
        args.max_depth,
        args.max_trees,
        args.top_k,
        args.dedup_mode,
        args.weight_mode,
        args.alpha,
        args.rule_weights,
        args.enable_classical,
        args.enable_derived_facts,
        args.max_derived_facts,
    ))

if __name__ == '__main__':
    main()
