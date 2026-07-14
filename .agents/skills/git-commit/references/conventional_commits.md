# Reference: Conventional Commits Guidelines

When drafting, validating, or executing Git commits, you must strictly adhere to the specification and specific formatting rules defined below.

## Message Format

```plain
<type>(<scope>): <description>

[optional body]

[optional footer(s)]
```

## Allowed Types

* **feat**: A new feature for the user.
* **fix**: A bug fix for the user.
* **docs**: Documentation only changes.
* **style**: Changes that do not affect the meaning of the code (formatting, missing semi-colons, etc).
* **refactor**: A code change that neither fixes a bug nor adds a feature.
* **perf**: A code change that improves performance.
* **test**: Adding missing tests or correcting existing tests.
* **build**: Changes that affect the build system or external dependencies.
* **ci**: Changes to CI configuration files and scripts.
* **chore**: Other changes that do not modify src or test files.
* **revert**: Reverts a previous commit.

## Strict Constraints

1. **Default Message Language**:
   * **The commit message must be written exclusively in English** unless the user provides explicit, specific instructions to use another language for that particular commit.

2. **Line Length Limits**:
   * The subject line (first line) must not exceed 72 characters, ideally 50 characters or less.
   * **Every single line within the commit message body must also be wrapped at 72 characters or less.** If an explanation runs longer, you must manually insert line breaks to keep each line under the 72-character threshold.

3. **Part Separation via Multiple `-m` Flags (At Most Three)**:
   * Use at most one `-m` flag per structural part: the subject line, the body, and the footer. Use at most three `-m` flags in total.
   * **NEVER split body lines or bullet lists across multiple `-m` flags.** Doing so inserts unwanted blank lines because Git automatically treats each `-m` flag as a separate paragraph.
   * **DO NOT use escape sequences like `\n` in double quotes.** Shells like bash will treat `\n` as literal backslash-n characters and commit them as-is.
   * **Use literal newlines (actual line breaks)** inside double quotes to write multi-line bodies or footers.
   * *Example:*

     ```bash
     git commit -m "feat(auth): add jwt authentication" -m "Validate tokens on every incoming request.
     Secure endpoints by rejecting expired credentials.
     - Added middleware for token validation
     - Removed legacy session handling" -m "BREAKING CHANGE: The old session-based cookie auth is deprecated."
     ```


4. **Co-authored-by Restriction**:
   * **Do not include any `Co-authored-by:` trailers** in the commit message or footer unless the user explicitly requests you to add credit for a co-author.

5. **Case and Punctuation**:
   * The description line must be written in lowercase and must not end with a period.

6. **Imperative Mood**:
   * Always use the imperative mood in the description (e.g., use "add", "fix", "change" instead of "added", "fixes", "changed").
