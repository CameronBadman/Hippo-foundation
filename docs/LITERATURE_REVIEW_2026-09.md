# Commissioned literature review — 2026-09-02

## Provenance and status

Commissioned by the repository owner on 2026-09-02 during the E1 gamma-sweep GPU
phase, and produced by a Claude research task with web search from a prompt
written in this repository's working session. It is stored here as a **source
document**: transcribed unaltered below, in the same discipline the
preregistration uses, so that what was actually returned can be separated from
what this project later concluded from it.

**None of its citations, quotations, dates, or venues have been independently
verified in this repository.** The report flags two of its own anchors (GROVER,
Graph-BERT) as recalled without a retrieved source. Everything else it claims to
have retrieved. Until spot-checked, treat every quotation as second-hand.

Two claims carry more decision weight than the rest and should be verified
first, because conclusions in `DESIGN_NOTES_READ_PATH_SUCCESSOR.md` rest on
them:

1. The 2018 characterisation of spurious search trajectories in multi-hop
   knowledge-graph reasoning. This is the basis for treating the failure this
   project measured as the canonical one rather than a novelty.
2. The reported false-negative rate among self-mined hard negatives in dense
   retrieval. This is one of the two independent arguments for precomputing an
   ablation ladder rather than deriving it from the trained model.

**Hidden-field scan exception.** The committed-artifact scan reports one hit on
this file, on the line beginning "What the evidence supports: Proof-gating is a
principled", where the flagged token is an ordinary English verb rather than a
data field and carries no episode content. The source text is **not** edited to
satisfy a mechanical check; the exception is recorded here instead so it stays
auditable, and so that any further hit on this file is compared against this one
rather than waved through. This note is deliberately worded to avoid adding
further false positives of its own.

What this project concluded from the report — including one place where the
report's prescription does not apply to this codebase — is recorded separately
in `DESIGN_NOTES_READ_PATH_SUCCESSOR.md` section 2.7. That section is analysis
and is not part of the source document; this file is not edited to agree with
it.

---

# Learned, Budget-Limited Graph Traversal with Proof-Gated Correctness: Where the Field Stands (2022–2026) and What to Build Next

## TL;DR

- **Budget-limited learned traversal is an active line, not a dead end** — but the specific failure the user measured (a model that collapses to 0.27% when a similarity feature is flattened) is the canonical, well-documented failure mode of RL/agentic graph reasoners (spurious paths, policy collapse onto cheap terminal-reward-correlated features). The fixes that actually worked in the literature are *process-level supervision* and *precomputed structural constraints*, not adversarial data deletion.
- **The ablation curriculum (direction a) is "known-disappointing," not known-good.** The structurally identical body of work — AFLite/adversarial filtering, Dynabench/DADC, and the "Whac-A-Mole" shortcut literature — repeatedly shows that removing the feature a weak heuristic uses makes the benchmark *harder* but usually pushes models to the *next* shortcut rather than to the intended reasoning. Pursue it only as a diagnostic/eval set, not as the primary training lever.
- **Build direction (b) — masked-node reconstruction for insert — but do not assume transfer.** Graph masked-reconstruction pretraining has a documented negative-transfer history; it helps most when the pretext objective is *aligned* with the downstream task (here it plausibly is, since "retrieve what a deleted node attached to" ≈ link/neighborhood reconstruction). Direction (c), unifying read+insert as one retrieve-and-select primitive, is the highest-value bet and is corroborated by the retrieval and KGQA literature.

## Key Findings

- **Proof-gated correctness (crediting an answer only when its evidence path decodes) is rare but not novel.** Multi-hop QA uses **Joint EM/F1** (answer AND supporting facts both correct) as a standard *reported* metric, and neurosymbolic/proof-generation work (ProofWriter, EntailmentBank "Overall-AllCorrect") uses strict all-or-nothing proof scoring. Making the proof a hard *gate on the primary correctness signal* — as the user does — is a stronger stance than the field's norm, and it is defensible: it is exactly the discipline that prevents the "right answer, wrong reason" pathology documented across NLI, VQA, KGQA, and neurosymbolic AI.
- **Parameterless shortcut baselines are standard practice** in every adjacent subfield: hypothesis-only NLI (Poliak et al. 2018), question-only/blindfold VQA and EmbodiedQA, claim-only fact verification, and the frequency-rule baseline for KG completion (CoDEx). The user's untrained similarity-walk baseline is methodologically orthodox and is the correct way to establish shortcut prevalence.
- **Self-mined hard negatives (ANCE-style) have a well-quantified failure mode — false negatives.** RocketQA (Qu et al., NAACL 2021) manually examined top-retrieved passages for 100 questions and found ~70% were actually positive: *"We find that about 70% of them are actually positives or highly relevant. Hence, it is likely to bring noise if we simply sample hard negatives from the top-retrieved passages."* Training on such passages as negatives produces conflicting gradients and degrades performance. This is a direct warning for any model-dependent ablation curriculum: if you delete "the heuristic-preferred path" using the current model's own scores, you risk deleting *correct* paths.

## Q1. Learned budget-limited graph traversal — where it stands now

**Anchors verified.** DeepPath (Xiong, Hoang, Wang, EMNLP 2017) is confirmed as the first RL path-reasoning method; MINERVA (Das et al., ICLR 2018) is confirmed as the REINFORCE walk-based query-answering agent with a recurrent (LSTM) history encoder that reaches a target without precomputed paths. Both anchors exist as described.

**What replaced them.** The line evolved along two branches:

1. *RL with better reward/exploration (2018–2023).* MultiHopKG / "Multi-Hop KG Reasoning with Reward Shaping" (Lin, Socher, Xiong, EMNLP 2018) added (a) reward shaping from a pretrained KG-embedding model to fix false-negative rewards and (b) **action dropout** to counter spurious paths. This paper is the single most important one for the user because it names the exact pathology (verbatim, arXiv 1808.10568): *"since no golden action sequence is used for training, the agent can be misled by spurious search trajectories that incidentally lead to the correct answer"* and *"Since there are usually more spurious paths than correct ones, spurious paths are often found first, and following exploration can be increasingly biased towards them."* That is policy collapse onto a cheap surface feature, described in 2018 and never fully solved by RL alone. Follow-ups: M-Walk (Shen et al., NeurIPS 2018, MCTS + value function for sparse reward), DacKGR (Lv et al., 2020, sparse KGs), SQUIRE (2022, seq2seq framework), RARL (Findings ACL 2021, rule-aware exploration to suppress spurious paths), and "Path Spuriousness-aware RL" (EACL 2023), which introduces a quantitative Path-Spuriousness metric and PS-guided reward — direct evidence the spurious-path problem is still an open, actively-worked line in 2023.
2. *LLM-as-agent traversal (2023–2026).* This is where the field actually landed. Think-on-Graph (Sun et al., ICLR 2024) casts an LLM as an agent doing beam search on a KG, exploring/pruning relations under a search-depth budget — training-free, and explicitly motivated by *knowledge traceability*; it "achieves overall SOTA in 6 out of 9 datasets" (WebQSP, GrailQA, QALD10-en, WebQuestions, Zero-Shot RE, Creak) "where most previous SOTAs rely on additional training." Reasoning-on-Graphs / RoG (Luo et al., ICLR 2024) uses a plan-retrieve-reason framework where relation paths are generated as "faithful plans," then grounded in the KG. ToG-2.0 (2024) and ToG-3.0 (2025) extend to hybrid text+KG retrieval; Search-on-Graph (2025) and Plan-on-Graph/Debate-on-Graph (2024–2025) add verification and iterative navigation. These are budget-limited (beam width, search depth, edge/latency budgets) learned/prompted traversal systems — so the user's problem framing is squarely an active research area.

**Transformer traversal (Graph-BERT, GROVER, Graphormer).** Graphormer (Ying et al., NeurIPS 2021, "Do Transformers Really Perform Bad for Graph Representation?") encodes structure via shortest-path-distance attention bias, degree centrality, and edge encodings. Its documented limitations matter for the user: (i) attention is **quadratic in node count**, limiting scale; (ii) Graphormer-GD (2023) showed plain shortest-path-distance *cannot* distinguish some structural perturbations; (iii) "Attending to Graph Transformers" (2023) empirically found graph transformers **generalize poorly to larger graphs** (e.g., Triangles) and that Graphormer is theoretically capped (e.g., ~90% on CSL because SPD distinguishes only 9 of 10 classes). Net: transformer traversal is powerful for fixed-size molecular graphs but has known generalization/expressivity ceilings and no special immunity to shortcut learning.

- **What the evidence supports:** Budget-limited learned traversal is an active, funded line (RoG was DARPA-supported). The user's 100%-at-128-edges result is consistent with what trained traversers achieve on small graphs.
- **What it warns against:** The 0.27%-when-flattened result is the textbook spurious-path/policy-collapse failure named since 2018. RL-only fixes (reward shaping, action dropout, diversity) *mitigate* but do not *eliminate* it; the durable fixes are process supervision and structural grounding.
- **What it is silent on:** None of these systems adopt the user's *proof-as-gate* correctness definition or the user's synthetic "sequence-of-relation-types query" setup exactly; the user is operating in a lightly-populated niche.

## Q2. Adversarial dataset filtering — genuine reasoning or the next shortcut?

**Anchors verified.** AFLite originates in Sakaguchi et al. 2020 (WinoGrande) and is formalized in Le Bras et al., "Adversarial Filters of Dataset Biases" (ICML 2020). It iteratively removes examples that ensembles of weak linear classifiers (over a fixed representation) predict correctly, i.e., examples a weak heuristic already solves — structurally identical to the user's direction (a).

**The pro case.** Le Bras et al. (2020) claim filtered data yields "better generalization to out-of-distribution tasks." Verbatim (arXiv 2002.04108): *"filtering results in a large drop in model performance (e.g., from 92% to 62% for SNLI), while human performance still remains high"*; elsewhere the paper reports "the best model on SNLI-AFLite achieves only 63% accuracy, a 30% drop."

**The 2022–2026 skeptical verdict (this is what matters for direction a):**

- *Phang, Chen, Huang, Bowman, "Adversarially Constructed Evaluation Sets Are More Challenging, but May Not Be Fair"* (DADC workshop @ ACL 2022; arXiv 2111.08181). Verbatim: adversarial filtering makes data harder but "the relative order of model performance is not preserved, with large random variation in model ranks as stronger adversaries are used," and "AFLite oversamples examples with low annotator agreement, meaning that model comparisons hinge on the most contentiously labeled examples." Also: an adversarial set "may be so narrowly optimized toward stumping a particular model that they no longer accurately measure the abilities that the dataset was designed to test."
- *Li et al., "A Whac-A-Mole Dilemma: Shortcuts Come in Multiples Where Mitigating One Amplifies Others"* (CVPR 2023). This is the strongest direct evidence for the "next shortcut down" hypothesis. Verbatim: "mitigating one shortcut amplifies reliance on others"; models "regardless of training set, architecture, and supervision — struggle when multiple shortcuts are present. Even methods explicitly designed to combat shortcuts struggle in a Whac-A-Mole dilemma."
- *Wallace, Williams, Jia, Kiela, "Analyzing Dynamic Adversarial Training Data in the Limit"* (Findings of ACL 2022). Even the proponents concede prior DADC "does not necessarily lead to better generalization beyond adversarial test data," and their positive result (26% fewer errors) required **20 rounds** on a deliberately tiny premise set. Few-round DADC (the realistic ANLI regime) does not reliably transfer.
- *Jiang & Bansal, "Avoiding Reasoning Shortcuts" (ACL 2019)* is the direct multi-hop-QA analogue: after building adversarial documents that break the word-match shortcut in HotpotQA, "after adversarial training, the baseline's performance improves but is still limited on the adversarial test" — i.e., the model does not fully convert to genuine multi-hop reasoning.

- **What the evidence supports:** Adversarial filtering reliably makes a benchmark harder and is a legitimate *diagnostic*; WANLI (Liu et al., EMNLP 2022) shows a *constructive* variant (cartography-guided generation) can improve OOD (+11% HANS, +9% ANLI).
- **What it warns against:** As a *training curriculum to force reasoning*, deleting heuristic-solvable examples predominantly surfaces the next shortcut and can oversample contentious/mislabeled examples. Direction (a) is "known-disappointing" as a primary training lever.
- **What it is silent on:** The user's setting is synthetic with a *known, decodable* ground-truth path — so unlike NLI/VQA there is no annotator-agreement problem and no ambiguity about the intended reasoning. This materially weakens the strongest objection (contentious labels) and is the one respect in which the user's direction (a) could outperform the pessimistic literature. Note also: no dedicated 2022–2026 paper cleanly *replicates or refutes* AFLite's training-side OOD-reasoning claim; the skepticism is concentrated on evaluation fairness.

## Q3. Masked node/edge reconstruction as graph pretraining — does it transfer?

**Anchors verified.** GraphMAE (Hou et al., KDD 2022) masks node features and reconstructs them with a scaled-cosine error; GraphMAE2 (2023) extends it. The masked-node insert objective the user proposes (delete a node, retrieve what it attached to) is essentially masked reconstruction / denoising link reconstruction.

**Negative-transfer evidence (what the user asked for):**

- *Hu et al., "Strategies for Pre-training GNNs"* (ICLR 2020). The foundational negative result, stated verbatim: naive strategies "give limited improvement and can even lead to **negative transfer** on many downstream tasks"; graph-level supervised pretraining alone caused negative transfer on many individual tasks, and *only* combining node-level + graph-level pretraining avoided it. Their Table 1 explicitly shades negative-transfer cells.
- *You, Chen, Wang, Shen, "When Does Self-Supervision Help GCNs?"* (ICML 2020): self-supervision helps only under specific schemes (pretraining+finetuning and multi-task), and gains are often within noise (~0.8 accuracy, comparable to std dev) — i.e., frequently not real.
- *Task-alignment is decisive.* Multiple surveys (Graph Prompt Learning survey 2023; Graph SSL survey) note edge-reconstruction pretext "concentrates solely on structural aspects, neglecting node properties, and may encounter challenges when applied to graph-level downstream tasks," and that a large pretext-downstream gap can yield performance "even worse than learning from scratch." Conversely, "Pre-Training GNNs for Generic Structural Feature Extraction" (2019) found **link classification benefits most from denoising link reconstruction**, because both "rely on robust representation of node pairs."
- *A GraphMAE-specific caveat:* GraphMAE, by reconstructing *features* not edges, "does not perform well on link prediction tasks as it does not try to minimize edge reconstruction error" (Generative and Contrastive Graph Representation Learning, 2025). Directly relevant: for an *insert/link-recovery* capability, the user wants an *edge/structure*-reconstruction objective, not GraphMAE's feature-reconstruction objective.
- *GSTBench (CIKM 2025)* and cross-dataset transfer studies confirm graph SSL transferability across *different* graphs remains weak and unsolved.

- **What the evidence supports:** Masked reconstruction *does* transfer when the pretext is aligned with the downstream task; the user's insert task (recover a deleted node's attachments) is *link/neighborhood reconstruction*, which is exactly the case where denoising link reconstruction transfers well. This is a favorable alignment.
- **What it warns against:** Do not import a GraphMAE-style *feature*-masking objective and expect it to help *structural retrieval*; and do not assume any pretraining gain without an ablation vs. from-scratch — negative transfer is common and gains are often within noise.
- **What it is silent on:** Whether masked-node pretraining improves the *read/traversal* task specifically (the transfer direction the user ultimately cares about for unification) — no paper tests this exact cross-task transfer.

## Q4. Hard negatives mined from the model's own outputs — model-dependent curricula

**Anchor verified.** ANCE (Xiong et al., ICLR 2021) periodically re-indexes the corpus with a recent checkpoint to mine the current model's hardest negatives.

**Known failure modes:**

- *False negatives.* RocketQA (Qu et al., NAACL 2021, arXiv 2010.08191) manually inspected top-retrieved passages for 100 questions and found ~70% were actually positive or highly relevant; introducing un-denoised hard negatives "significantly decreases" retriever performance because training on them "punishes the model for correct predictions." A 2026 survey states false-negative contamination "can degrade performance by 10–15% in challenging domains."
- *Contamination worsens as the model improves* — "increasingly contaminated by false positives as the retriever improves" (When Hard Negatives Hurt, 2026). This is the curriculum-collapse risk: the better your model, the more its self-mined "hard negatives" are actually correct answers.
- *Source-dependent shortcuts.* Naïvely mixing model-generated negatives "introduces source-dependent shortcuts that corrupt optimization dynamics" (When Hard Negatives Hurt, 2026).
- *Mitigations that work:* denoising/relabeling suspected false negatives (teacher/cross-encoder or LLM cascades), top-k filtering to drop overly-hard negatives, and momentum/teleportation negatives (ANCE-Tele, 2022) to reduce catastrophic forgetting.

- **What the evidence supports:** Model-dependent hard-example mining is powerful *when* false negatives are filtered.
- **What it warns against:** A model-dependent ablation curriculum (deleting the "heuristic-preferred path" using the current model's own preference ordering) is structurally identical to self-mined negatives and inherits the false-negative pathology: you may delete the *correct* path, and the risk grows as the model improves.
- **What it is silent on:** In the user's *synthetic* setting the ground-truth path is known exactly, so false negatives are avoidable by construction — which argues strongly for a **precomputed** ablation (delete based on the *baseline heuristic's* fixed scores, not the trained model's evolving scores).

## Q5. Is proof-gated evaluation standard?

- **Multi-hop QA:** Supporting-fact scoring is standard as a *separate* metric, and **Joint EM/F1** (both answer and supporting facts correct) is standard in HotpotQA and successors (2WikiMultiHopQA, MuSiQue). Cognitive Graph (Ding et al., ACL 2019) even proposed JointEM/AnsEM as a "logical rigor" ratio (reporting 33.4% vs a 7.9% baseline). So proof-as-a-metric is fully established; proof-as-a-*gate* on the headline number is a stricter, less common choice.
- **Neurosymbolic / proof generation:** EntailmentBank (Dalvi et al., EMNLP 2021) uses "Overall-AllCorrect" (whole proof tree must be perfect); ProofWriter (Tafjord et al., 2021) uses strict "Full Accuracy" (proof graph must exactly match gold, else 0) and emphasizes *faithful* proofs assembled from actual inference steps rather than post-hoc. These are proof-gated in spirit.
- **Known pathology — the "right answer, wrong reason":** The neurosymbolic "reasoning shortcuts" literature (Marconato et al., NeurIPS 2023, "Not All Neuro-Symbolic Concepts Are Created Equal"; Bortolotti et al.; van Krieken et al. 2024–2025) formally shows NeSy predictors "attain high accuracy but by leveraging concepts with unintended semantics." Proof-gating is precisely the defense: it refuses credit for correct answers reached via wrong concepts. Note a subtlety these papers raise: strict AllCorrect metrics "do not account for the existence of multiple valid trees/proofs" — if the user's task admits multiple valid decoding paths, a naive single-gold-path gate will under-credit correct reasoning.

- **What the evidence supports:** Proof-gating is a principled, defensible, and increasingly-motivated stance; it directly targets the failure mode the user is worried about.
- **What it warns against:** Strict single-path gates can be unfair when multiple valid proofs exist; ensure the gate accepts any valid decoding path, not one canonical path.
- **What it is silent on:** No standard benchmark makes proof-decoding *the* correctness definition in budget-limited graph *traversal* specifically — the user is ahead of standard practice here, which is a contribution, not a mistake.

## Q6. Are parameterless shortcut baselines standard?

Yes — this is orthodox and arguably best practice:

- **Hypothesis-only NLI** (Poliak et al., *StarSem 2018*): a model seeing only the hypothesis beats majority class across ~10 NLI datasets (e.g., 71% on SNLI, 61% on MultiNLI vs 33% chance), exposing artifacts; the authors "advocate for its inclusion in future dataset reports." Gururangan et al. 2018 concurrently.
- **Question-only / blindfold baselines**: question-only VQA (the VQA-CP line) and "Blindfold Baselines for Embodied QA" (2018), where a question-only model matches or beats full navigation+vision models except when the agent is spawned very close to the target.
- **Claim-only fact verification** (Schuster et al., 2019, FEVER).
- **KG completion frequency baseline**: CoDEx (Safavi & Koutra, EMNLP 2020, arXiv 2009.07810) shows a trivial frequency rule covers a large fraction of FB15k-237 relations, and the best embedding (RESCAL) beat that baseline on FB15k-237 by only +0.120 MRR (0.236→0.356) versus +0.202 on CoDEx-M (0.135→0.337); the baseline "performs on par with or even outperforms the embedding on FB15K-237 for some relation types." FB15k→FB15k-237 itself exists because inverse-relation leakage let trivial baselines win.

- **What the evidence supports:** The user's untrained similarity-walk baseline is exactly the right instrument, and building it "specifically to make the trained model look worse" is the correct adversarial-baseline mindset. Shortcut prevalence is normally established precisely this way.
- **What it warns against:** Nothing — this is the one methodological choice the literature unambiguously endorses.
- **What it is silent on:** How to set a *budget-matched* shortcut baseline (same 128-edge budget) — the user's budget-matched design is a refinement beyond standard practice and strengthens the argument.

## Recommendations

**Pursue direction (c) first (unify read + insert as one retrieve-and-select primitive).** This is the highest-value bet and the best-supported: the entire 2023–2026 KGQA-agent literature (ToG, RoG, Search-on-Graph) is converging on a single retrieve-then-select-then-reason loop, and the retrieval literature treats read and write/index as the same embedding space. Unification also lets the insert objective regularize the read policy against surface shortcuts.

**Build direction (b) (masked-node insert) — but as edge/structure reconstruction, not GraphMAE feature masking, and always ablate against from-scratch.** The transfer case is favorable *because* your insert task is link/neighborhood recovery, the one regime where denoising link reconstruction reliably transfers. Benchmark to change course: if masked-node pretraining does not beat from-scratch by more than one standard deviation on the read task, treat it as negative transfer and drop it (this is the exact threshold Hu et al. and You et al. used).

**Demote direction (a) (ablation curriculum) to a diagnostic, not a training driver — and if used, make it precomputed, not model-dependent.** The AFLite/Whac-A-Mole/DADC evidence says deleting heuristic-solvable examples mostly surfaces the next shortcut. Two caveats make your case less bleak than the literature's: (i) your ground-truth path is known, so you avoid the annotator-agreement and false-negative pathologies *if* you delete based on the **fixed baseline heuristic's** scores rather than the **evolving trained model's** scores (Q4); (ii) a synthetic task has an enumerable shortcut set, so you can in principle ablate *all* known shortcuts at once (the Whac-A-Mole paper's prescription) rather than one at a time.

**Single most valuable experiment.** Run a *counterfactual, budget-matched* test of relation-following with the shortcut *precomputed-out of the answer's reachability*, not merely flattened at eval time. Concretely: construct training/eval graphs where the highest-similarity walk provably leads to a *wrong* answer class, so the only path that decodes is the relation-type-following one, and the deletion is defined by the *parameterless baseline's fixed scores* (model-independent, per Q4). Then measure proof-gated accuracy (accepting any valid decoding path, per Q5). This single experiment discriminates the three hypotheses the whole report turns on: (1) if proof-gated accuracy stays high, the model *can* learn relation-following once the shortcut is denied — direction (a) is worth keeping as a curriculum; (2) if it collapses toward the ~0.27% floor, the model is shortcut-dependent and you need architectural grounding (RoG-style plan-then-ground) rather than data ablation; (3) if it lands between (like the +17-point gap over the pure similarity walk), you have quantified exactly how much genuine relation-following the model already has. Benchmarks that change the decision: proof-gated accuracy > ~90% ⇒ ship the curriculum; < ~40% ⇒ pivot to structural grounding; in between ⇒ invest in process supervision (path-spuriousness-style rewards, EACL 2023).

## Caveats

- **Single-group / single-benchmark risks.** The neurosymbolic "reasoning shortcuts" consensus rests heavily on one research cluster (Marconato/Teso/Vergari/van Krieken and collaborators); treat its framing as strong-but-concentrated. The KGQA-agent SOTA claims (ToG's 6/9 datasets) rest largely on WebQSP and CWQ among a handful of benchmarks — narrow evidence. The "AFLite yields genuine OOD reasoning" claim rests essentially on Le Bras et al. 2020 and has *not* been cleanly re-confirmed nor cleanly refuted by a dedicated 2022–2026 training-side replication; the skepticism is concentrated on the *evaluation-fairness* side (Phang et al. 2022).
- **Domain transfer of negative results.** The strongest "next shortcut down" evidence (Whac-A-Mole) is from computer vision; NLP/graph analogues (Jiang & Bansal 2019; DADC) point the same way but are individually weaker. The convergence across modalities is what makes the conclusion credible.
- **What I could not source.** I found no paper that (a) makes proof-decoding the *gate* on correctness in budget-limited graph traversal, (b) tests whether masked-node pretraining transfers specifically to a learned traversal/read task, or (c) is a direct negative replication of AFLite's training-side OOD claim. Where the user is operating without direct precedent, that is noted as a contribution opportunity rather than a gap to be filled from adjacent work.
- **Recalled-without-source (flagged):** GROVER (2020) and Graph-BERT (2020) I recall as ~2020 transformer/pretraining-on-graph systems but did not retrieve primary sources for in this pass; treat their attribution as unverified. All other named papers above were retrieved and quoted from primary or authoritative secondary sources.
