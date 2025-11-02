"""Script to clean up sys.path manipulation in test files."""

import re
from pathlib import Path


def find_test_files(root_dir: Path) -> list[Path]:
    """Find all Python test files in the project."""
    return list(root_dir.glob("**/test_*.py")) + list(root_dir.glob("**/test/*.py"))

def remove_sys_path_manipulation(content: str) -> tuple[str, bool]:
    """Remove sys.path manipulation code from file content."""
    lines = content.splitlines()
    modified = False
    
    # Patterns to identify sys.path manipulation
    patterns = [
        r"sys\.path\.insert\s*\(\s*0\s*,\s*.*\)",  # sys.path.insert(0, ...)
        r"sys\.path\.append\s*\(.*\)",                # sys.path.append(...)
        r"sys\.path\s*\+=\s*\[.*\]",                  # sys.path += [...]
        r"if.*not in sys\.path.*sys\.path\.insert",      # if ... not in sys.path: sys.path.insert(...)
    ]
    
    # Also track the import of sys if it's only used for path manipulation
    has_other_sys_usage = any(re.search(r"\bsys\.(?!path\b)", line) for line in lines)
    
    # Find and remove matching lines
    new_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Skip docstrings and comments
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
            new_lines.append(line)
            i += 1
            continue
            
        # Check for multi-line statements
        if any(re.search(pattern, line) for pattern in patterns):
            # Check if this is part of a multi-line statement
            if line.rstrip().endswith("\\"):
                # Skip until we find the end of the statement
                while i < len(lines) and lines[i].rstrip().endswith("\\"):
                    i += 1
                # Skip the last line of the statement
                i += 1
                modified = True
                continue
            # Single line statement, just skip it
            i += 1
            modified = True
            continue
                
        new_lines.append(line)
        i += 1
    
    # Remove 'import sys' if it's only used for path manipulation and not used elsewhere
    if not has_other_sys_usage and "import sys" in "\n".join(new_lines):
        new_lines = [
            line for line in new_lines 
            if not re.match(r"^\s*import sys\s*(?:#.*)?$", line) 
            and not re.match(r"^\s*import sys,", line)
        ]
        modified = True
    
    return "\n".join(new_lines), modified

def process_file(file_path: Path, dry_run: bool = True) -> tuple[bool, str]:
    """Process a single file and remove sys.path manipulation if found."""
    try:
        content = file_path.read_text(encoding="utf-8")
        new_content, modified = remove_sys_path_manipulation(content)
        
        if modified:
            if not dry_run:
                file_path.write_text(new_content, encoding="utf-8")
            return True, content
        return False, ""
    except Exception as e:
        error_msg = f"Error processing {file_path}: {e}"
        print(error_msg)
        return False, error_msg

def show_diff(original: str, modified: str, file_path: Path) -> None:
    """Show a diff between original and modified content."""
    from difflib import unified_diff
    
    original_lines = original.splitlines(keepends=True)
    modified_lines = modified.splitlines(keepends=True)
    
    diff = unified_diff(
        original_lines, 
        modified_lines,
        fromfile=f"Original: {file_path}",
        tofile=f"Modified: {file_path}",
        n=3
    )
    
    print("".join(diff))

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Clean up sys.path manipulation in test files.")
    parser.add_argument("--apply", action="store_true", help="Apply the changes (default: dry run)")
    args = parser.parse_args()
    
    project_root = Path(__file__).parent.parent
    test_files = find_test_files(project_root)
    
    print(f"Found {len(test_files)} test files to check...")
    print(f"Mode: {'DRY RUN' if not args.apply else 'APPLYING CHANGES'}\n")
    
    modified_count = 0
    for file_path in test_files:
        modified, original_content = process_file(file_path, dry_run=not args.apply)
        if modified:
            modified_count += 1
            print(f"\n{'[WOULD MODIFY]' if not args.apply else '[MODIFIED]'} {file_path.relative_to(project_root)}")
            
            # For dry run, show the diff
            if not args.apply:
                new_content = remove_sys_path_manipulation(original_content)[0]
                show_diff(original_content, new_content, file_path)
    
    print(f"\nDone! {'Would modify' if not args.apply else 'Modified'} "
          f"{modified_count} out of {len(test_files)} files.")
    if not args.apply:
        print("\nRun with --apply to actually make these changes.")

if __name__ == "__main__":
    main()
