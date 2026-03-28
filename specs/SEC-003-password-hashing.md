# SEC-003: Upgrade Password Hashing — MD5 → bcrypt

## Problem
CodeQL alerts #72 and #74:
- `variable.py:104` — MD5 used for sensitive password hashing (weak algorithm)
- `__init__.py:342` — Clear-text storage of sensitive data (stored hash is MD5, trivially reversible)

Currently passwords are stored as `md5(password)` in the config. MD5 is fast and
reversible via rainbow tables — a poor choice for password storage.

## Current Auth Flow

**Config stores:** `md5(password)` — 32-char hex string

**Login form (`login_post`):**
```python
md5(form.get('password', '')) == password  # md5 of submitted == stored md5
```

**API key endpoint (`get_key`):**
```python
p_param == password  # client sends raw md5 hash, compared directly to stored md5
```

## Target Auth Flow

**Config stores:** `$2b$12$...` — bcrypt hash of `md5(password)`

Store `bcrypt(md5(password))` not `bcrypt(password)`. This:
1. Preserves backward compat with the `getkey` endpoint (client still sends MD5 in transit)
2. Massively upgrades the stored security (bcrypt vs MD5)
3. Allows transparent migration on next login

**Login form:** `bcrypt.checkpw(md5(submitted_password).encode(), stored_hash.encode())`
**getkey:** `bcrypt.checkpw(p_param.encode(), stored_hash.encode())`

## Backward Compatibility (Migration)

When a user logs in:
1. Check if stored password starts with `$2b$` → bcrypt path
2. If it looks like a 32-char hex MD5 hash → legacy path:
   - Verify the old way (`md5(submitted) == stored`)
   - On success: upgrade stored hash to `bcrypt(md5(submitted))`
   - Continue logging in normally

## Implementation Plan

### 1. Add bcrypt dependency
Add to `requirements.txt`:
```
bcrypt==4.3.0
```

### 2. New helper functions in `couchpotato/core/helpers/variable.py`

```python
def hash_password(raw_password: str) -> str:
    """Hash a password for secure storage using bcrypt(md5(password)).
    
    We bcrypt the MD5 hash (not raw password) to maintain compatibility
    with the /getkey API endpoint which accepts MD5 hashes from clients.
    """
    import bcrypt
    pw_md5 = md5(raw_password)
    return bcrypt.hashpw(pw_md5.encode('utf-8'), bcrypt.gensalt(rounds=12)).decode('utf-8')


def check_password(submitted_md5_or_raw: str, stored_hash: str, is_md5: bool = False) -> bool:
    """Verify a password against a stored hash.
    
    Handles both bcrypt (new) and MD5 (legacy) stored hashes.
    
    Args:
        submitted_md5_or_raw: The submitted value — either raw password or MD5 hash
        stored_hash: The stored hash from config
        is_md5: If True, submitted_md5_or_raw is already an MD5 hash (getkey endpoint)
    
    Returns:
        True if password matches
    """
    import bcrypt
    if not stored_hash:
        return True  # No password configured
    
    # Determine the MD5 representation to check against stored bcrypt hash
    pw_md5 = submitted_md5_or_raw if is_md5 else md5(submitted_md5_or_raw)
    
    if stored_hash.startswith('$2b$') or stored_hash.startswith('$2a$'):
        # bcrypt hash — modern path
        try:
            return bcrypt.checkpw(pw_md5.encode('utf-8'), stored_hash.encode('utf-8'))
        except Exception:
            return False
    else:
        # Legacy MD5 hash — check and caller should upgrade
        return pw_md5 == stored_hash
```

### 3. Update `couchpotato/__init__.py`

**login_post:** Replace `md5(form.get('password', '')) == password` with:
- Call `check_password(form.get('password', ''), password, is_md5=False)`
- If legacy MD5 match: upgrade stored password with `hash_password(form.get('password', ''))`

**get_key:** Replace `p_param == password` with:
- Call `check_password(p_param, password, is_md5=True)`

### 4. No change to getkey client behaviour
The JavaScript client that calls `/getkey?p=<md5>` continues to send the MD5 hash.
The server now bcrypt-checks the received MD5 hash against `bcrypt(md5(password))`.

## Tests to Write (TDD — write these FIRST)

```python
# tests/unit/test_password_hashing.py

def test_hash_password_returns_bcrypt_hash():
    """hash_password should return a bcrypt hash string."""
    from couchpotato.core.helpers.variable import hash_password
    h = hash_password('mysecretpassword')
    assert h.startswith('$2b$')
    assert len(h) == 60

def test_hash_password_is_not_deterministic():
    """Two calls with same input should produce different hashes (salt)."""
    from couchpotato.core.helpers.variable import hash_password
    h1 = hash_password('password123')
    h2 = hash_password('password123')
    assert h1 != h2

def test_check_password_bcrypt_correct():
    """check_password should return True for correct password against bcrypt hash."""
    from couchpotato.core.helpers.variable import hash_password, check_password
    stored = hash_password('correcthorsebatterystaple')
    assert check_password('correcthorsebatterystaple', stored, is_md5=False) is True

def test_check_password_bcrypt_wrong():
    """check_password should return False for wrong password against bcrypt hash."""
    from couchpotato.core.helpers.variable import hash_password, check_password
    stored = hash_password('correcthorsebatterystaple')
    assert check_password('wrongpassword', stored, is_md5=False) is False

def test_check_password_legacy_md5_correct():
    """check_password should return True for correct legacy MD5 hash."""
    from couchpotato.core.helpers.variable import md5, check_password
    stored = md5('mypassword')  # Legacy: stored as MD5
    assert check_password('mypassword', stored, is_md5=False) is True

def test_check_password_legacy_md5_wrong():
    """check_password should return False for wrong legacy MD5 hash."""
    from couchpotato.core.helpers.variable import md5, check_password
    stored = md5('mypassword')
    assert check_password('wrongpassword', stored, is_md5=False) is False

def test_check_password_getkey_style_bcrypt():
    """getkey sends md5 hash — check_password with is_md5=True should work."""
    from couchpotato.core.helpers.variable import hash_password, check_password, md5
    stored = hash_password('mypassword')
    p_param = md5('mypassword')  # What getkey client sends
    assert check_password(p_param, stored, is_md5=True) is True

def test_check_password_empty_stored_hash():
    """No password configured — always returns True."""
    from couchpotato.core.helpers.variable import check_password
    assert check_password('anything', '', is_md5=False) is True
    assert check_password('', '', is_md5=False) is True
```

## Acceptance Criteria
- [ ] All tests in `test_password_hashing.py` pass
- [ ] Login works with both old (MD5) and new (bcrypt) stored passwords
- [ ] MD5 passwords are automatically upgraded to bcrypt on successful login
- [ ] `/getkey` endpoint still works (client sends MD5 hash, server bcrypt-checks)
- [ ] `pytest tests/unit/ -q` — ALL 660+ tests pass
- [ ] `ruff check .` — clean
- [ ] Commit: `feat: upgrade password hashing from MD5 to bcrypt with migration (SEC-003)`

## Notes
- bcrypt rounds=12 is standard — ~250ms per hash on modern hardware, fine for login
- Don't change how the password is DISPLAYED or CONFIGURED by users — they still set their
  password in plain text in the web UI; hashing happens when it's saved to config
- This does NOT fix the transit security of `/getkey` (still sends MD5 over HTTP) — that's
  a separate concern and acceptable for a local-only app
- Suppress the CodeQL alert at variable.py:104 with `# noqa` after migration since md5() 
  is still used for non-password purposes (cache keys, etc.)
