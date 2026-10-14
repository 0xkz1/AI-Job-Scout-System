import os
from typing import Dict, List

class ContextLoader:
    """
    Loads and prepares context fragments from Kazuki's personal knowledge base.
    Optimized for Phase 2: High-precision, low-noise retrieval of core identity/philosophy.
    """

    # Order matters more than the list does. Callers truncate this text — the
    # context scorer takes the first 9,000 characters of ~50,000 — so whatever
    # sorts first is what the model actually reads, and os.listdir order is the
    # filesystem's, not anyone's judgement. It put roadmap.md's career-strategy
    # essay in front of skills.md, profile.md and timeline.md, all three of
    # which fell off the end. A scorer asked whether the candidate can do a job
    # was answering without their skills, employment history or education.
    #
    # So the persona is stated, most load-bearing first, and anything unlisted
    # follows in sorted order (a new persona file is still read, just after
    # these). Every entry is the English original; _ja.md translations are
    # skipped by the caller as duplicates of what is already here.
    PRIORITY = (
        "profile.md",       # who they are professionally, in one page
        "skills.md",        # what they can do — the axis role_fit judges on
        "timeline.md",      # employment history, dated
        "about.md",         # the projects, in prose
        "ethos.md",         # how they choose work
        "cover-letter-evidence.md",
        "education.md",
        "interests.md",
        "contact.md",
        # life_goal.md and roadmap.md are deliberately NOT in this list — they
        # read as "the job funds my real goal", which is true of every posting
        # equally and discriminates between none of them. ethos.md used to
        # carry a "Life Goal — Artist" section that did the same thing to
        # role_fit judgments: asked whether the candidate can do THIS job, the
        # model had "well, any job funds the art" sitting in the same prompt.
        # Left unlisted, they still load (PRIORITY is a preference, not a
        # filter) but sort after everything ranked here, and the per-file cap
        # + the scorer's overall truncation mean they are the first casualty
        # when the persona does not fit the budget — which is the right file
        # to lose first.
    )

    # Management files, agent instructions, and documents that are OUTPUT of
    # this pipeline rather than input to it. CLAUDE.md is a rule sheet for
    # coding agents ("use context_search instead of reading files", "respond in
    # compressed style") and was being read as a description of the candidate.
    # The *_cv_CV.md files are generated CVs for specific companies: feeding a
    # tailored artefact back in as persona lets one application's phrasing
    # colour the scoring of every later posting.
    EXCLUDE = {"AGENTS.md", "README.md", "CLAUDE.md"}

    def __init__(self, base_dir: str = "/media/kz003/atelier/00_Kazuki/"):
        self.base_dir = base_dir
        self.exclude_files = set(self.EXCLUDE)
        self.context_fragments: List[Dict[str, str]] = []

    def _is_persona_file(self, name: str) -> bool:
        if not name.endswith(".md") or name.endswith("_ja.md"):
            return False
        if name in self.exclude_files:
            return False
        # Generated per-company CVs, e.g. LBD_Studio_cv_CV.md.
        return not name.endswith("_CV.md")

    def load_all_contexts(self) -> List[Dict[str, str]]:
        """Top-level persona files, most load-bearing first."""
        self.context_fragments = []

        if not os.path.exists(self.base_dir):
            return []

        found = {f for f in os.listdir(self.base_dir) if self._is_persona_file(f)}
        ordered = [f for f in self.PRIORITY if f in found]
        ordered += sorted(found - set(self.PRIORITY))

        for file in ordered:
            fragment = self._parse_file(os.path.join(self.base_dir, file))
            if fragment:
                self.context_fragments.append(fragment)

        return self.context_fragments

    def _parse_file(self, file_path: str) -> Dict[str, str]:
        """Reads a file and returns its content as a context fragment."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
            
            if not content:
                return {}

            return {
                "source": os.path.basename(file_path),
                "content": content
            }
        except Exception as e:
            # In a production system, we'd log this properly.
            return {}

    # Per-file cap, applied before joining. Callers cut the combined text — the
    # context scorer keeps 9,000 of ~45,000 characters — and a single cut at the
    # end means one long file can spend the whole budget: skills.md is 12,128
    # characters on its own, so profile.md and skills.md together filled the
    # scorer's window and timeline, about and ethos never arrived at all. A
    # per-file cap costs the tail of the longest documents and buys the
    # existence of the rest, which is the better trade when the question is
    # "what kind of work is this person for".
    PER_FILE_CHARS = 3200

    def get_combined_context_string(self) -> str:
        """Formats all fragments into a single block for LLM context injection."""
        if not self.context_fragments:
            return ""

        parts = []
        for frag in self.context_fragments:
            content = frag["content"]
            if len(content) > self.PER_FILE_CHARS:
                content = content[:self.PER_FILE_CHARS].rsplit("\n", 1)[0] + "\n…"
            parts.append(f"--- Source: {frag['source']} ---\n{content}")

        return "\n\n".join(parts)

if __name__ == "__main__":
    # Quick verification script
    loader = ContextLoader()
    contexts = loader.load_all_contexts()
    print(f"Found {len(contexts)} valid context fragments.")
    for c in contexts:
        print(f"- {c['source']}")
