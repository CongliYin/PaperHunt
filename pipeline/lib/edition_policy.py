"""Source-independent, conservative admission rules on title and abstract."""

import re

EVO = "agent-harness-evolution"
MEM = "agent-memory"
MM = "agent-multimodal"
SHOP = "agent-e-commerce"

PHYSICAL = r"robot(?:s|ic\w*)?|embodi\w*|3\s?d|three dimensional|vision language action|vla|autonomous driv\w*|self driving|cameras?|lidar|physical ai|humanoid\w*|manipulators?|autonomous vehicles?"
MODAL = r"multi ?modal\w*|omni(?:modal\w*| modality)?|omni[- ]?llms?|vision language|vision|visual\w*|imagery|images?|video\w*|audio\w*|auditory|speech|voices?|acoustic\w*|vlms?|mllms?|text to image"
AGENT = r"agents?|agentic|assistants?|self improv\w*|self evol\w*|self referential|harness\w*"
EVOLVE = r"self improv\w*|self evol\w*|self modif\w*|co evol\w*|evol\w*|harness\w*|agent training|train(?:ing)? (?:language |llm )?agents|trajectory|trajectories|reinforcement learning|feedback loop|policy optimi\w*|policy update\w*|skill learn\w*|skill induction|experience distillation"
MEMORY = r"memor(?:y|ies|ization)|remember\w*|episodic|forgetting|continual learning|lifelong learning|fast weights?"
MM_TASK = r"memor\w*|long term|turn taking|full duplex|tool call\w*|tool use|tool routing|interactive|interaction|streaming|orchestrat\w*|harness\w*|self evol\w*|self improv\w*"
COMMERCE = r"shopping|shoppers?|e ?commerce|catalog\w*|products?|sku|retail"
LANGUAGE = r"conversation\w*|dialog\w*|natural language|preferenc\w*|clarif\w*|shopping agent\w*|shopping assistant\w*|user request\w*"
MATCH = r"search\w*|retriev\w*|ranking|recommend\w*|matching|selection|product choice|product comparison"


def normalized(paper):
    text = (paper["title"] + " " + paper["abstract"]).casefold()
    return re.sub(r"[-‐‑–—/]", " ", text).replace("camera ready", "")


def eligible(domain, paper):
    text = normalized(paper)

    def hit(pattern):
        return re.search(r"\b(?:" + pattern + r")\b", text) is not None

    if domain in (EVO, MEM, MM) and hit(PHYSICAL):
        return False
    if domain in (EVO, MEM) and (hit(MODAL) or hit(r"world model\w*")):
        return False
    if domain == EVO:
        return hit(AGENT) and hit(EVOLVE)
    if domain == MEM:
        return hit(AGENT) and hit(MEMORY)
    if domain == MM:
        return hit(MODAL) and hit(MM_TASK) and (hit(AGENT) or hit(MEMORY))
    if domain == SHOP:
        return hit(COMMERCE) and hit(LANGUAGE) and hit(MATCH)
    return True


def value(row):
    # Integer percentage; empirical evidence has the largest weight.
    return 6 * row["M"] + 9 * row["E"] + 5 * row["U"]


def winner(rows, min_fit=4, min_value=60):
    ranked = [
        d
        for d, r in rows.items()
        if not r["needs_text"]
        and r["F"] >= min_fit
        and r["M"] >= 2
        and r["E"] >= 2
        and value(r) >= min_value
    ]
    order = (SHOP, MM, MEM, EVO)
    return min(
        ranked,
        key=lambda d: (
            -rows[d]["F"],
            -value(rows[d]),
            order.index(d) if d in order else len(order),
            d,
        ),
        default=None,
    )
