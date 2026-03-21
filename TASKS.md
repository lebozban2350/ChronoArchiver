# TASKS.md

- [x] **v1.0.3: Final Ship & Polish (Latest)**
  - [x] Integrity: Fix `efficientdet_lite0.tflite` SHA-256 hash
  - [x] Cleanup: Remove stale comments in `tabs.py`
  - [x] Cleanup: Delete unused `use_gpu` in `tabs.py`
  - [x] Refactor: Move `hashlib` and `queue` imports to top level
  - [x] Release: Bump version to `v1.0.3`

- [x] **v1.0.2: Regression Fixes & Refinement**
  - [x] Fix crash: `NameError: filename` in `av1_tab.py`
  - [x] Security: Update official face model hash
  - [x] UX: Fix swapped file counters in AI Scanner lists
  - [x] Cleanup: Remove redundant loops in `organizer.py`
  - [x] Consistency: Fix CRLF in `logger.py`
  - [x] Release: Bump version to `v1.0.2`

- [x] **v1.0.1: Code Review & Stability Overhaul**
  - [x] **Fix Crash Bugs**
    - [x] `pathlib` imports in `organizer.py` and `scanner.py`
    - [x] `logger.py`: Fix path handling & platformdirs
  - [x] **Fix Logic Bugs**
    - [x] `updater.py`: Semantic version comparison
    - [x] `scanner.py` & `tabs.py`: Fix inverted naming (Keep/Move)
    - [x] `organizer.py`: Validate dates with `strptime`
    - [x] `av1_tab.py`: Implement `maintain_structure`
  - [x] **Cleanup Code Smells**
    - [x] `requirements.txt`: Remove unused `PySide6`
    - [x] `model_manager.py`: Add SHA-256 integrity checks
    - [x] `organizer.py`: Move all imports to top
    - [x] `logger.py`: Fix line endings & `.gitattributes`
    - [x] `tabs.py`: Use PayPal.me/Venmo handles for donations
  - [x] **Verify & Final Version Bump (1.0.1)**

- [x] **v1.0.0: Initial Release**
  - [x] Initialize project structure and artifacts
  - [x] Research source codebases
  - [x] Port `Media_Archive_Organizer` (Theme & Core)
  - [x] Port `Mass_AV1_Encoder` as a tab
  - [x] Implement LLM model check & download feature
  - [x] Verify merged application
