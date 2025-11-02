#!/usr/bin/env python3
"""Script to update imports in test files."""

import os
import re


def update_imports(file_path):
    """Update imports in a test file."""
    with open(file_path, encoding="utf-8") as f:
        content = f.read()
    
    # Check if the file already has the updated import pattern
    if "from pathlib import Path" in content and "project_root = str(Path(__file__).parent.parent.parent)" in content:
        return False  # Already updated
    
    # Remove any existing sys.path manipulation
    content = re.sub(r'^import sys\s+sys\.path\.insert\(0, ["\'].*?["\']\)\s+', "", content, flags=re.MULTILINE)
    
    # Add the new import pattern if not present
    if "from pathlib import Path" not in content:
        content = content.replace(
            '"""',
            '"""\n\nimport sys\nfrom pathlib import Path\n\n# Add the project root to the Python path\nproject_root = str(Path(__file__).parent.parent.parent)\nif project_root not in sys.path:\n    sys.path.insert(0, project_root)\n\n',
            1
        )
    
    # Write the updated content back to the file
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
    
    return True

def main():
    """Main function to update all test files."""
    test_dirs = [
        "tests/unit",
        "tests/integration",
        "tests/functional",
        "tests/e2e",
        "tests"  # For test files directly in the tests directory
    ]
    
    updated_files = []
    
    for test_dir in test_dirs:
        if not os.path.exists(test_dir):
            continue
            
        for root, _, files in os.walk(test_dir):
            for file in files:
                if file.startswith("test_") and file.endswith(".py"):
                    file_path = os.path.join(root, file)
                    try:
                        if update_imports(file_path):
                            updated_files.append(file_path)
                    except Exception as e:
                        print(f"Error updating {file_path}: {e}")
    
    if updated_files:
        print("Updated imports in the following files:")
        for file in updated_files:
            print(f"- {file}")
    else:
        print("No files needed updating.")

if __name__ == "__main__":
    main()
