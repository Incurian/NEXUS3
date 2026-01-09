# Code Review: nexus3/skill/ Module

**Reviewed:** 2026-01-08
**Reviewer:** Claude Opus 4.5
**Module:** `nexus3/skill/`
**Files Reviewed:** 15 files (5 core + 9 builtin + 1 README)

---

## Executive Summary

The skill module is well-designed with clear separation of concerns, good use of protocols for flexibility, and comprehensive documentation. The code follows Python best practices and the project's established patterns. There are minor improvements possible around type safety, error handling consistency, and a few edge cases.

**Overall Grade: B+**

---

## 1. Code Quality and Organization

### Strengths

- **Clear file separation**: Each file has a single responsibility
  - `base.py` - Protocol and base class definitions
  - `registry.py` - Skill management and instantiation
  - `services.py` - Dependency injection container
  - `errors.py` - Exception hierarchy

- **Consistent code style**: All files follow the same patterns for imports, docstrings, and type hints

- **Good module exports** (`__init__.py:26-39`): Clean public API with explicit `__all__`

### Issues

**Minor: Unused import in `builtin/__init__.py`**

```
File: nexus3/skill/builtin/__init__.py:7
```

The `register_builtin_skills` is imported from `registration.py` but also re-exported. This is fine, but the individual factory imports (lines 3-6) are only used for `__all__` exports. Consider if users really need direct factory access or if they should go through `register_builtin_skills`.

**Minor: Echo skill not in registration**

```
File: nexus3/skill/builtin/registration.py
```

The `echo_skill_factory` exists in `echo.py` but is not registered by `register_builtin_skills()`. This is documented in the README (line 181) as intentional, but creates an inconsistency - the skill exists but is not available by default. Consider either:
1. Adding it to registration for testing purposes
2. Moving `echo.py` to a `tests/` directory

---

## 2. Skill Protocol Design

### Strengths

- **Runtime checkable protocol** (`base.py:16-17`): Allows `isinstance()` checks at runtime

- **Well-documented protocol** (`base.py:17-108`): Excellent docstrings with examples

- **Flexible implementation options**: Can implement protocol directly or use `BaseSkill`

- **Properties over methods** for metadata (`name`, `description`, `parameters`): Prevents accidental modification

### Issues

**Consideration: Protocol return type coupling**

```python
File: nexus3/skill/base.py:97
async def execute(self, **kwargs: Any) -> ToolResult:
```

The protocol is tightly coupled to `ToolResult` from `nexus3.core.types`. This is reasonable for this project, but worth noting that the skill system cannot be used standalone without the core module.

**Suggestion: Parameter validation hook**

The protocol has no mechanism for validating parameters before execution. Skills must handle validation internally in `execute()`. Consider adding an optional `validate()` method to the protocol for pre-execution validation:

```python
def validate(self, **kwargs: Any) -> list[str]:
    """Return list of validation errors, empty if valid."""
    ...
```

---

## 3. Registry and Dependency Injection

### Strengths

- **Lazy instantiation** (`registry.py:99-103`): Skills only created when first used, saving resources

- **Instance caching** (`registry.py:69`): Same instance returned on subsequent calls

- **Re-registration handling** (`registry.py:84-85`): Clears cache when skill is re-registered

- **Factory pattern** (`registry.py:32`): Clean separation of creation from registration

### Issues

**Bug: Potential name mismatch**

```python
File: nexus3/skill/registry.py:128-134
definitions.append({
    "type": "function",
    "function": {
        "name": skill.name,  # Uses skill.name
        ...
    }
})
```

The registry uses the registered name (from `_factories` keys) to look up skills, but returns `skill.name` in definitions. If these don't match, tool calls will fail:

```python
registry.register("foo", lambda _: EchoSkill())  # Registered as "foo"
# But EchoSkill.name returns "echo", so LLM sees "echo" in definitions
# When LLM calls "echo", registry.get("echo") returns None
```

**Recommendation**: Either validate that registered name matches `skill.name`, or use the registered name consistently in `get_definitions()`.

**Missing: Unregister method**

```python
File: nexus3/skill/registry.py
```

The `ServiceContainer` has `unregister()` but `SkillRegistry` does not. For dynamic skill management (e.g., loading/unloading plugins), an `unregister()` method would be useful.

**Type Safety: `get()` return type**

```python
File: nexus3/skill/registry.py:87
def get(self, name: str) -> Skill | None:
```

This is correct, but callers must always handle `None`. Consider adding a `require()` method similar to `ServiceContainer`:

```python
def require(self, name: str) -> Skill:
    """Get skill or raise SkillNotFoundError."""
    skill = self.get(name)
    if skill is None:
        raise SkillNotFoundError(name)
    return skill
```

---

## 4. Built-in Skill Implementations

### Strengths

- **Consistent structure**: All skills follow the same pattern (class + factory function)

- **Proper error handling**: File skills handle multiple exception types (`read_file.py:54-63`)

- **Cross-platform paths**: Uses `normalize_path()` for path handling (`read_file.py:51`, `write_file.py:56`)

- **UTF-8 encoding**: Explicit encoding everywhere (`read_file.py:52`, `write_file.py:58`)

### Issues

**Type Coercion Risk: request_id conversion**

```python
File: nexus3/skill/builtin/nexus_send.py:63
result = await client.send(content, int(request_id) if request_id else None)

File: nexus3/skill/builtin/nexus_cancel.py:58
result = await client.cancel(int(request_id))
```

The `request_id` parameter is typed as `str` but converted to `int` without try/except. If the LLM provides a non-numeric string, this will raise `ValueError` which is not caught:

```python
# LLM sends: {"request_id": "abc123"}
int("abc123")  # ValueError: invalid literal for int()
```

**Recommendation**: Add try/except for the int conversion or validate the format.

**Inconsistent Error Message Casing**

```python
File: nexus3/skill/builtin/nexus_send.py:57
return ToolResult(error="No url provided")  # Lowercase 'url'

File: nexus3/skill/builtin/nexus_cancel.py:52
return ToolResult(error="No URL provided")  # Uppercase 'URL'
```

Minor inconsistency in error message capitalization.

**Missing: Binary file handling in read_file**

```python
File: nexus3/skill/builtin/read_file.py:60-61
except UnicodeDecodeError:
    return ToolResult(error=f"File is not valid UTF-8 text: {path}")
```

This is good, but consider adding an option to read binary files as base64 for images/PDFs.

**Security: write_file path traversal**

```python
File: nexus3/skill/builtin/write_file.py:56-58
p = normalize_path(path)
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(content, encoding="utf-8")
```

There's no restriction on where files can be written. A malicious prompt could write to system directories if permissions allow. The `normalize_path()` function resolves paths, but doesn't restrict them. Consider:
1. Adding a configurable allowed_paths list
2. Preventing writes outside the working directory by default

This is likely intentional for a trusted agent, but worth documenting the security implications.

---

## 5. ServiceContainer Patterns

### Strengths

- **Simple design** (`services.py:29-130`): No framework complexity, just a typed dict wrapper

- **Clear semantics**: `get()` returns None, `require()` raises KeyError

- **Dataclass implementation** (`services.py:29`): Clean and Pythonic

- **Complete API**: `register`, `unregister`, `has`, `get`, `require`, `clear`, `names`

### Issues

**Type Safety: `Any` return types**

```python
File: nexus3/skill/services.py:56, 67
def get(self, name: str) -> Any:
def require(self, name: str) -> Any:
```

Services are stored and returned as `Any`, losing type information. This is a pragmatic choice for simplicity, but callers must cast:

```python
pool: AgentPool = cast(AgentPool, services.get("agent_pool"))
```

Consider a generic pattern for type-safe access:

```python
T = TypeVar('T')

def get_typed(self, name: str, type_: type[T]) -> T | None:
    service = self._services.get(name)
    if service is not None and isinstance(service, type_):
        return service
    return None
```

**Missing: Service lifecycle hooks**

For services that need cleanup (database connections, HTTP clients), there's no dispose/shutdown mechanism. Consider adding:

```python
async def close_all(self) -> None:
    """Close all services that implement Closable."""
    for service in self._services.values():
        if hasattr(service, 'close'):
            await service.close()
```

---

## 6. Documentation Quality

### Strengths

- **Excellent README** (`README.md`): 469 lines of comprehensive documentation

- **Clear examples**: Code examples for all major use cases

- **Type tables**: Quick reference tables for types and files

- **Data flow diagram** (`README.md:407-426`): ASCII art showing system architecture

- **Good docstrings**: All public methods have docstrings with Args/Returns sections

### Issues

**README: Outdated parallel execution info**

```
File: nexus3/skill/README.md:295-316
```

The parallel execution section describes `_parallel` flag in tool arguments, but this isn't implemented in the skill module itself - it would be in the session/executor. Verify this feature exists or remove the documentation.

**README: Missing error examples**

The "Creating New Skills" section (`README.md:317-385`) shows only success cases. Consider adding examples of returning `ToolResult(error=...)` for error conditions.

**Minor: BaseSkill docstring example**

```python
File: nexus3/skill/base.py:136-137
async def execute(self, input: str = "", **kwargs: Any) -> ToolResult:
    return ToolResult(output=f"Result: {input}")
```

The example uses `input` as a parameter name, which shadows the Python builtin. Use `value` or `text` instead.

---

## 7. Potential Issues and Improvements

### Critical Issues

None identified.

### High Priority

1. **Name mismatch validation** (`registry.py`): Add validation that registered name matches skill.name

2. **request_id type coercion** (`nexus_send.py`, `nexus_cancel.py`): Add try/except for int conversion

### Medium Priority

3. **Add `require()` to SkillRegistry**: Match ServiceContainer pattern for mandatory skill access

4. **Add `unregister()` to SkillRegistry**: Enable dynamic skill management

5. **Consistent error messages**: Standardize capitalization and format

### Low Priority

6. **Type-safe service access**: Consider generic methods for typed service retrieval

7. **Service lifecycle**: Add cleanup mechanism for disposable services

8. **Binary file support**: Consider base64 encoding option for read_file

---

## 8. Test Coverage Analysis

### Existing Tests

- `tests/unit/test_skill_registry.py` (353 lines): Comprehensive unit tests for ServiceContainer, SkillRegistry, and EchoSkill
- `tests/integration/test_skill_execution.py` (552 lines): Integration tests for Session with skills

### Test Quality

**Strengths**:
- Good coverage of happy paths
- Tests for edge cases (empty messages, extra kwargs, re-registration)
- Mock provider pattern for integration tests
- Tests for max iterations safety

**Missing Coverage**:
- No tests for `read_file`, `write_file`, or `sleep` skills
- No tests for `nexus_*` skills (network-dependent)
- No tests for error cases in file operations
- No tests for `BaseSkill` abstract class directly

**Recommendation**: Add unit tests for built-in skills with mocked filesystem/network.

---

## 9. Code Metrics

| File | Lines | Functions/Classes | Complexity |
|------|-------|-------------------|------------|
| `base.py` | 186 | 2 classes | Low |
| `registry.py` | 155 | 1 class, 6 methods | Low |
| `services.py` | 130 | 1 class, 7 methods | Low |
| `errors.py` | 25 | 3 classes | Very Low |
| `echo.py` | 51 | 1 class, 1 function | Very Low |
| `read_file.py` | 76 | 1 class, 1 function | Low |
| `write_file.py` | 80 | 1 class, 1 function | Low |
| `sleep.py` | 51 | 1 class, 1 function | Very Low |
| `nexus_send.py` | 79 | 1 class, 1 function | Low |
| `nexus_cancel.py` | 74 | 1 class, 1 function | Low |
| `nexus_status.py` | 71 | 1 class, 1 function | Low |
| `nexus_shutdown.py` | 68 | 1 class, 1 function | Low |
| `registration.py` | 31 | 1 function | Very Low |

**Total**: ~1,100 lines of code (excluding tests and README)

---

## 10. Summary of Recommendations

### Must Fix
- Validate registered name matches skill.name in `SkillRegistry.register()`
- Add try/except for `int(request_id)` conversions in nexus_* skills

### Should Fix
- Add `require()` method to SkillRegistry
- Add `unregister()` method to SkillRegistry
- Standardize error message formatting
- Add unit tests for built-in skills

### Nice to Have
- Type-safe service retrieval with generics
- Service lifecycle/cleanup mechanism
- Binary file support in read_file
- Parameter validation hook in Skill protocol

---

## Appendix: File Locations

| File | Path |
|------|------|
| Module init | `/home/inc/repos/NEXUS3/nexus3/skill/__init__.py` |
| Skill protocol | `/home/inc/repos/NEXUS3/nexus3/skill/base.py` |
| Registry | `/home/inc/repos/NEXUS3/nexus3/skill/registry.py` |
| Services | `/home/inc/repos/NEXUS3/nexus3/skill/services.py` |
| Errors | `/home/inc/repos/NEXUS3/nexus3/skill/errors.py` |
| README | `/home/inc/repos/NEXUS3/nexus3/skill/README.md` |
| Builtin init | `/home/inc/repos/NEXUS3/nexus3/skill/builtin/__init__.py` |
| Registration | `/home/inc/repos/NEXUS3/nexus3/skill/builtin/registration.py` |
| Echo | `/home/inc/repos/NEXUS3/nexus3/skill/builtin/echo.py` |
| Read file | `/home/inc/repos/NEXUS3/nexus3/skill/builtin/read_file.py` |
| Write file | `/home/inc/repos/NEXUS3/nexus3/skill/builtin/write_file.py` |
| Sleep | `/home/inc/repos/NEXUS3/nexus3/skill/builtin/sleep.py` |
| Nexus send | `/home/inc/repos/NEXUS3/nexus3/skill/builtin/nexus_send.py` |
| Nexus cancel | `/home/inc/repos/NEXUS3/nexus3/skill/builtin/nexus_cancel.py` |
| Nexus status | `/home/inc/repos/NEXUS3/nexus3/skill/builtin/nexus_status.py` |
| Nexus shutdown | `/home/inc/repos/NEXUS3/nexus3/skill/builtin/nexus_shutdown.py` |
| Unit tests | `/home/inc/repos/NEXUS3/tests/unit/test_skill_registry.py` |
| Integration tests | `/home/inc/repos/NEXUS3/tests/integration/test_skill_execution.py` |
