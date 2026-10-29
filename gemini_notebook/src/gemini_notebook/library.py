"""
Notebook Library Management for NotebookLM
Manages a library of NotebookLM notebooks with metadata
Based on the MCP server implementation
"""

import json
from datetime import datetime
from typing import Any

from .config import DATA_DIR, LIBRARY_FILE


class NotebookLibrary:
    """Manages a collection of NotebookLM notebooks with metadata"""

    def __init__(self):
        """Initialize the notebook library"""
        self.data_dir = DATA_DIR
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.library_file = LIBRARY_FILE
        self.notebooks: dict[str, dict[str, Any]] = {}
        self.active_notebook_id: str | None = None

        # Load existing library
        self._load_library()

    def _load_library(self):
        """Load library from disk"""
        if self.library_file.exists():
            try:
                with open(self.library_file) as f:
                    data = json.load(f)
                    self.notebooks = data.get("notebooks", {})
                    self.active_notebook_id = data.get("active_notebook_id")
            except Exception as e:
                print(f"⚠️ Error loading library: {e}")
                self.notebooks = {}
                self.active_notebook_id = None
        else:
            self._save_library()

    def _save_library(self):
        """Save library to disk"""
        try:
            data = {
                "notebooks": self.notebooks,
                "active_notebook_id": self.active_notebook_id,
                "updated_at": datetime.now().isoformat(),
            }
            with open(self.library_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"❌ Error saving library: {e}")

    def add_notebook(
        self,
        url: str,
        name: str,
        description: str,
        topics: list[str],
        content_types: list[str] | None = None,
        use_cases: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Add a new notebook to the library

        Args:
            url: NotebookLM notebook URL
            name: Display name for the notebook
            description: What's in this notebook
            topics: Topics covered
            content_types: Types of content (optional)
            use_cases: When to use this notebook (optional)
            tags: Additional tags for organization (optional)

        Returns:
            The created notebook object
        """
        # Generate ID from name
        notebook_id = name.lower().replace(" ", "-").replace("_", "-")

        # Check for duplicates
        if notebook_id in self.notebooks:
            raise ValueError(f"Notebook with ID '{notebook_id}' already exists")

        # Create notebook object
        notebook = {
            "id": notebook_id,
            "url": url,
            "name": name,
            "description": description,
            "topics": topics,
            "content_types": content_types or [],
            "use_cases": use_cases or [],
            "tags": tags or [],
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "use_count": 0,
            "last_used": None,
        }

        # Add to library
        self.notebooks[notebook_id] = notebook

        # Set as active if it's the first notebook
        if len(self.notebooks) == 1:
            self.active_notebook_id = notebook_id

        self._save_library()

        print(f"✅ Added notebook: {name} ({notebook_id})")
        return notebook

    def remove_notebook(self, notebook_id: str) -> bool:
        """
        Remove a notebook from the library

        Args:
            notebook_id: ID of notebook to remove

        Returns:
            True if removed, False if not found
        """
        if notebook_id in self.notebooks:
            del self.notebooks[notebook_id]

            # Clear active if it was removed
            if self.active_notebook_id == notebook_id:
                self.active_notebook_id = None
                # Set new active if there are other notebooks
                if self.notebooks:
                    self.active_notebook_id = next(iter(self.notebooks.keys()))

            self._save_library()
            print(f"✅ Removed notebook: {notebook_id}")
            return True

        print(f"⚠️ Notebook not found: {notebook_id}")
        return False

    def update_notebook(
        self,
        notebook_id: str,
        name: str | None = None,
        description: str | None = None,
        topics: list[str] | None = None,
        content_types: list[str] | None = None,
        use_cases: list[str] | None = None,
        tags: list[str] | None = None,
        url: str | None = None,
    ) -> dict[str, Any]:
        """
        Update notebook metadata

        Args:
            notebook_id: ID of notebook to update
            Other args: Fields to update (None = keep existing)

        Returns:
            Updated notebook object
        """
        if notebook_id not in self.notebooks:
            raise ValueError(f"Notebook not found: {notebook_id}")

        notebook = self.notebooks[notebook_id]

        # Update fields if provided
        if name is not None:
            notebook["name"] = name
        if description is not None:
            notebook["description"] = description
        if topics is not None:
            notebook["topics"] = topics
        if content_types is not None:
            notebook["content_types"] = content_types
        if use_cases is not None:
            notebook["use_cases"] = use_cases
        if tags is not None:
            notebook["tags"] = tags
        if url is not None:
            notebook["url"] = url

        notebook["updated_at"] = datetime.now().isoformat()

        self._save_library()
        print(f"✅ Updated notebook: {notebook['name']}")
        return notebook

    def get_notebook(self, notebook_id: str) -> dict[str, Any] | None:
        """Get a specific notebook by ID"""
        return self.notebooks.get(notebook_id)

    def list_notebooks(self) -> list[dict[str, Any]]:
        """List all notebooks in the library"""
        return list(self.notebooks.values())

    def search_notebooks(self, query: str) -> list[dict[str, Any]]:
        """
        Search notebooks by query

        Args:
            query: Search query (searches name, description, topics, tags)

        Returns:
            List of matching notebooks
        """
        query_lower = query.lower()
        results = []

        for notebook in self.notebooks.values():
            # Search in various fields
            searchable = [
                notebook["name"].lower(),
                notebook["description"].lower(),
                " ".join(notebook["topics"]).lower(),
                " ".join(notebook["tags"]).lower(),
                " ".join(notebook.get("use_cases", [])).lower(),
            ]

            if any(query_lower in field for field in searchable):
                results.append(notebook)

        return results

    def select_notebook(self, notebook_id: str) -> dict[str, Any]:
        """
        Set a notebook as active

        Args:
            notebook_id: ID of notebook to activate

        Returns:
            The activated notebook
        """
        if notebook_id not in self.notebooks:
            raise ValueError(f"Notebook not found: {notebook_id}")

        self.active_notebook_id = notebook_id
        self._save_library()

        notebook = self.notebooks[notebook_id]
        print(f"✅ Activated notebook: {notebook['name']}")
        return notebook

    def get_active_notebook(self) -> dict[str, Any] | None:
        """Get the currently active notebook"""
        if self.active_notebook_id:
            return self.notebooks.get(self.active_notebook_id)
        return None

    def increment_use_count(self, notebook_id: str) -> dict[str, Any]:
        """
        Increment usage counter for a notebook

        Args:
            notebook_id: ID of notebook that was used

        Returns:
            Updated notebook
        """
        if notebook_id not in self.notebooks:
            raise ValueError(f"Notebook not found: {notebook_id}")

        notebook = self.notebooks[notebook_id]
        notebook["use_count"] += 1
        notebook["last_used"] = datetime.now().isoformat()

        self._save_library()
        return notebook

    def get_stats(self) -> dict[str, Any]:
        """Get library statistics"""
        total_notebooks = len(self.notebooks)
        total_topics = set()
        total_use_count = 0

        for notebook in self.notebooks.values():
            total_topics.update(notebook["topics"])
            total_use_count += notebook["use_count"]

        # Find most used
        most_used = None
        if self.notebooks:
            most_used = max(self.notebooks.values(), key=lambda n: n["use_count"])

        return {
            "total_notebooks": total_notebooks,
            "total_topics": len(total_topics),
            "total_use_count": total_use_count,
            "active_notebook": self.get_active_notebook(),
            "most_used_notebook": most_used,
            "library_path": str(self.library_file),
        }
