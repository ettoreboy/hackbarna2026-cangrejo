# Techniques reference

Written for: whoever writes the detection prompts and the evaluation rubric. One page per concept is too much; one paragraph each is the goal. Each entry gives a definition, what it looks like in a short post, the textual cues a model should look for, and a neutral example. Examples are invented and attributed to nobody.

Three groups: **manipulation tactics** (rhetorical moves aimed at emotion or identity), **logical fallacies** (defective reasoning, can be used innocently), and **psychological mechanisms** (what the tactics exploit; useful for the `cognitive_summary`, not as detection labels).

Use the **canonical names** in bold as the labels the model returns. The badge UI and the evaluation rubric key on them, so spelling must not drift.

---

## A. Manipulation tactics

### **Outrage Farming**
Posting content engineered to provoke moral indignation because indignation drives shares. The goal is the reaction, not the claim.
- **Looks like:** a single villain, a shocking detail, an implied "can you believe this", no proposal.
- **Cues:** moral-emotional vocabulary (disgusting, shameful, betrayal, they dare), rhetorical questions, "share if you agree", no data, no policy.
- **Example:** "They just voted to give themselves a raise while pensioners freeze. Unbelievable. RT so everyone sees this."
- **Prompt hint:** ask whether the post would lose its point if the emotional words were removed. If yes, it is farming.

### **Scapegoating**
Blaming a complex or multi-causal problem on one group.
- **Looks like:** economic, safety or cultural problem + one demographic named as the cause.
- **Cues:** "because of X", "X are the reason", totalising nouns (migrants, landlords, elites, the woke), no other cause mentioned.
- **Example:** "Rents are unaffordable because landlords are parasites. That is the whole story."
- **Prompt hint:** check if the named group is presented as the *sole* cause and whether any structural cause is acknowledged.

### **Fear-mongering**
Exaggerating a threat to trigger protective, fast, low-deliberation responses.
- **Looks like:** catastrophe language about an uncertain future, urgency, no probabilities.
- **Cues:** collapse, invasion, flood, destroy, lose our country, before it is too late, "they are coming for".
- **Example:** "The system is collapsing. In five years there will be nothing left to save."
- **Prompt hint:** distinguish from legitimate warning by checking for evidence, scope and hedging. Fear-mongering has none.

### **Dog Whistle**
Coded language that reads neutral to outsiders and carries a specific meaning to an in-group.
- **Looks like:** ordinary words, oddly emphasised, or numbers, symbols and phrases with known coded history.
- **Cues:** "globalists", "cosmopolitan elites", "certain neighbourhoods", "you know who", "(((…)))", 88, 14 words, "great replacement", "cultural Marxism".
- **Example:** "Ask yourself who really owns the media. The globalists don't want you to."
- **Prompt hint:** highest false-positive risk of any label. Require the model to name the coded meaning it believes is intended and rate its own confidence. Flag as Dog Whistle only when the phrase has a documented coded use.

### **Us-vs-Them Framing** (in-group / out-group)
Sorting the world into a virtuous "we" and a hostile "they" so that agreement becomes loyalty.
- **Looks like:** pronoun asymmetry, "real Germans", "ordinary people versus the elite", "patriots versus traitors".
- **Cues:** we/they density, purity words (real, true, genuine), traitor/enemy vocabulary.
- **Example:** "Real citizens work. The others live off your taxes and laugh at you."
- **Prompt hint:** this is what `is_division_tactic` measures. Set it true when the post's persuasive force comes from group membership rather than from the claim.

### **Dehumanization**
Describing people with vocabulary reserved for animals, disease, objects or waste.
- **Looks like:** parasites, vermin, plague, flood, swarm, garbage, invaders, "it" for a person.
- **Cues:** biological or hydraulic metaphors applied to humans.
- **Example:** "A swarm of them arrives every night."
- **Prompt hint:** flag on the metaphor alone. Intent is irrelevant; the metaphor does the work.

### **Emotional Bait** (engagement bait)
Soliciting an emotional reaction or interaction directly, independent of any claim.
- **Cues:** "Who agrees?", "Like if you remember", "Say it louder", "Tag someone who".
- **Example:** "Who else is DONE with this government? 🙋"
- **Prompt hint:** cheap to detect and low harm on its own. Report it but weigh it lightly in the score.

### **Manufactured Urgency**
Framing a slow or ongoing situation as a now-or-never moment.
- **Cues:** now, tomorrow, last chance, before Sunday, we have days left.
- **Example:** "Either we close the borders this week or we lose the country."
- **Prompt hint:** often co-occurs with False Dilemma and election timing. Note the calendar in `strategic_intent`.

### **Cherry Picking**
Presenting a true but unrepresentative fact as if it were the whole picture.
- **Cues:** one striking number or anecdote, no base rate, no trend, no comparison.
- **Example:** "Crime by foreigners up 30 % in one town." (with no national figure)
- **Prompt hint:** the model cannot verify the number. Ask it to state what comparison figure would be needed to evaluate the claim, and put that in `factual_context`.

### **Whataboutism**
Deflecting a criticism by pointing at a different wrong, usually by the critic's side.
- **Cues:** "And what about", "Funny how nobody mentions", "Where was the outrage when".
- **Example:** "They complain about our rally. Where was the outrage when their people blocked the motorway?"
- **Prompt hint:** a tactic when used to avoid the point; a fair comparison otherwise. Look for whether the original criticism is ever answered.

### **Gish Gallop**
Overwhelming with many weak claims so no single one can be addressed.
- **Cues:** long lists, numbered threads of allegations, "1/ 2/ 3/", no sources per item.
- **Prompt hint:** rare in a single tweet, common in threads. Note when the post is part of a thread.

### **Astroturfing / Manufactured Consensus**
Presenting a coordinated or small voice as a spontaneous popular movement.
- **Cues:** "everyone is saying", "the people have spoken", "millions agree", identical phrasing across accounts.
- **Prompt hint:** cannot be detected from one post. Detect the *claim* of consensus and flag it as unverified.

---

## B. Logical fallacies

### **False Dilemma** (also False Dichotomy)
Presenting two options as the only ones when more exist.
- **Cues:** either/or, "the choice is simple", "you are with us or against us".
- **Example:** "Either we stop all immigration or we lose our welfare state."
- **Note:** use **False Dilemma** as the canonical label; treat "False Dichotomy" as a synonym on input.

### **Ad Hominem**
Attacking the person instead of the argument.
- **Cues:** the reply addresses character, motive, looks, past, not the claim.
- **Example:** "Why listen to a minister who has never had a real job?"
- **Variants:** *tu quoque* ("you did it too"), *poisoning the well* (discrediting in advance), *guilt by association*.

### **Hasty Generalization**
Drawing a broad conclusion from a small or unrepresentative sample.
- **Cues:** one incident → "they all", "this is what happens every time".
- **Example:** "Another attack by an asylum seeker. This is who they are."

### **Slippery Slope**
Claiming one step must lead to an extreme outcome without showing the chain.
- **Cues:** "next they will", "it starts with X and ends with Y", "where does it stop".
- **Example:** "Today it is speed limits, tomorrow they ban cars."

### **Appeal to Fear**
Using fear as the reason to accept a conclusion. The fallacy form of Fear-mongering.
- **Cues:** "if you don't X, then [catastrophe]" with the catastrophe standing in for evidence.

### **Appeal to Emotion**
Substituting any emotion (pity, pride, anger) for evidence.
- **Cues:** anecdote about a child, a grandmother, a veteran, followed by a policy conclusion with no bridge.

### **Straw Man**
Distorting the opponent's position into a weaker one, then attacking that.
- **Cues:** "So they think…", "Their plan is basically…", quoting nobody.
- **Example:** "The Greens want you to freeze in the dark to save a beetle."

### **Middle Ground** (also Golden Mean, Argument to Moderation)
Assuming the position between two extremes is correct because it is in the middle.
- **Cues:** "both sides are extreme", "the sensible position is", "adults in the room".
- **Example:** "Radicals left and right want chaos. Only the centre can save democracy."
- **Note:** this is the centrist fallacy. Include it so the tool catches all sides.

### **Bandwagon** (Appeal to Popularity)
Something is right because many believe it.
- **Cues:** "everyone knows", "80 % of people agree", "nobody believes that anymore".

### **Appeal to Authority** (misplaced)
Citing an authority outside its competence or without the claim being checkable.
- **Cues:** "experts say", "a top doctor confirms", no name, no source.

### **Loaded Question**
A question with a built-in assumption.
- **Cues:** "Why does the government hate its own citizens?"

### **No True Scotsman**
Redefining a group to exclude counterexamples.
- **Cues:** "No real conservative would…", "a real feminist would never".

### **Post Hoc** (False Cause)
Assuming that because Y followed X, X caused Y.
- **Cues:** "since they took office, prices have doubled".

### **Motte and Bailey**
Advancing a bold claim, then retreating to a modest defensible one when challenged, and treating the defence as vindication of the bold claim.
- **Prompt hint:** needs the reply chain. Note when available.

---

## C. Psychological mechanisms (for the summary, not as labels)

### Moral contagion
Posts containing moral-emotional words (hate, shame, evil, betray, disgrace) spread further on social networks. Brady, Wills and colleagues measured roughly a 20 % increase in retweet rate per additional moral-emotional word in political tweets. Outrage Farming exploits this directly.

### Affective polarization
Disliking the other side's *people* more than disagreeing with their *positions*. Us-vs-Them framing, Dehumanization and Ad Hominem feed it. The tool should name it when the post's aim is hostility rather than persuasion.

### In-group solidarity / out-group hostility
Threat to the group tightens loyalty inside it. Fear-mongering plus Scapegoating is the classic pairing: create a threat, name a culprit, bond the audience.

### Negativity bias and threat salience
Negative and threatening information captures attention faster and is remembered longer. This is why fear posts outperform hope posts even when the hopeful claim is stronger.

### Identity-protective cognition
People evaluate evidence to protect group belonging rather than to find truth. It is why a fact-check alone rarely works, and why the tool teaches the *pattern* rather than declaring the post false.

### Inoculation (prebunking)
Exposure to a weakened form of a manipulation technique, plus an explanation of how it works, builds resistance to later encounters. Effects are measured in weeks and decay without reminders. The `cognitive_summary` should always end by naming the technique in general form so each analysis doubles as a booster.

### Illusory truth
Repetition increases perceived truth regardless of accuracy. Relevant to `strategic_intent` when a post repeats a known talking point rather than adding anything.

---

## D. How to use this for prompts

1. **One canonical list.** The bold names from sections A and B live in `backend/prompts/taxonomy.py` (`TACTICS`, `FALLACIES`, a synonym map, and `normalize_label`). The prompt builder injects them as the allowed vocabulary for `communication_signals[].name` and `logical_fallacies[].name`; the schema normalises whatever the model returns. Unlisted labels come back as "Other: <name>" so the list can grow from real output.
2. **Cues become the checklist.** For each label, the prompt can carry one line: the cues above. That is enough for Flash-class models; long definitions cost tokens and do not improve recall.
3. **Confidence for the risky labels.** Dog Whistle, Scapegoating and Dehumanization carry reputational risk if wrong. Ask for a 0 to 1 confidence and suppress the badge below 0.6.
4. **Score is a function of labels, not a free number.** A more defensible `manipulation_score` is computed server-side: weight each detected label (Dehumanization and Scapegoating high, Emotional Bait low), cap at 100. This makes the number explainable and stable across runs. Consider it for v1.1.
5. **Controls.** Every technique here has a left, right and centrist example available. When building the evaluation set, pick posts so each label appears at least once from each side.

## Further reading

- Brady, Wills, Jost, Tucker, Van Bavel (2017). Emotion shapes the diffusion of moralized content in social networks. *PNAS*.
- Roozenbeek, van der Linden et al. (2022). Psychological inoculation improves resilience against misinformation on social media. *Science Advances*.
- Iyengar, Lelkes, Levendusky, Malhotra, Westwood (2019). The origins and consequences of affective polarization. *Annual Review of Political Science*.
- Rathje, Van Bavel, van der Linden (2021). Out-group animosity drives engagement on social media. *PNAS*.
- Bennett, B. *Logically Fallacious* (reference catalogue of ~300 fallacies).
