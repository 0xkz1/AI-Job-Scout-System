import os
from typing import Dict, List

class ContextLoader:
    """
    Loads and prepares context fragments from Kazuki's personal knowledge base.
    Optimized for Phase 2: High-precision, low-noise retrieval of core identity/philosophy.
    """

    def __init__(self, base_dir: str = "/media/kz003/atelier/00_Kazuki/"):
        self.base_dir = base_dir
        # AGENTS and README are management files, not persona/context files.
        self.exclude_files = {"AGENTS.md", "README.md"}
        self.context_fragments: List[Dict[str, str]] = []

    def load_all_contexts(self) -> List[Dict[str, str]]:
        """Scans the directory for non-Japanese MD files (excluding management docs)."""
        self.context_fragments = []
        
        if not os.path.exists(self.base_dir):
            return []

        # We only look at the top level (no recursion) as per requirements.
        for file in os.listdir(self.base_dir):
            # Filter: .md files, not in exclude list, and NOT a Japanese version (_ja.md)
            if (file.endswith(".md") and 
                file not in self.exclude_files and 
                not file.endswith("_ja.md")):
                
                file_path = os.path.join(self.base_dir, file)
                fragment = self._parse_file(file_path)
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

    def get_combined_context_string(self) -> str:
        """Formats all fragments into a single block for LLM context injection."""
        if not self.context_fragments:
            return ""
        
        parts = []
        for frag in self.context_fragments:
            parts.append(f"--- Source: {frag['source']} ---\n{frag['content']}")
        
        return "\n\n".join(parts)

if __name__ == "__main__":
    # Quick verification script
    loader = ContextLoader()
    contexts = loader.load_all_contexts()
    print(f"Found {len(contexts)} valid context fragments.")
    for c in contexts:
        print(f"- {c['source']}")
