"""Dashboard sign-in: password hashing, account lookup, role rules, lockout."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dashboard"))
import auth  # noqa: E402


def test_hash_roundtrip_and_salt():
    h1, h2 = auth.hash_password("secret"), auth.hash_password("secret")
    assert h1 != h2                                   # random salt
    assert auth.verify_password("secret", h1) and auth.verify_password("secret", h2)
    assert not auth.verify_password("Secret", h1)


def test_verify_rejects_malformed_hashes():
    for bad in ["", "plain", "md5$1$00$00", "pbkdf2_sha256$x$zz$00", None]:
        assert not auth.verify_password("secret", bad)


def test_demo_accounts_match_their_published_passwords():
    users, is_demo = auth.load_users(None)
    assert is_demo
    for name, pw in auth.DEMO_PASSWORDS.items():
        user = auth.authenticate(name, pw, users)
        assert user is not None and user.username == name
    assert auth.authenticate("driver", "driver-demo", users).truck == "T05"
    assert auth.authenticate("dispatcher", "driver-demo", users) is None


def test_username_is_case_and_space_insensitive():
    users, _ = auth.load_users(None)
    assert auth.authenticate("  Dispatcher ", "dispatch-demo", users).role == "Dispatcher"
    assert auth.authenticate("nobody", "dispatch-demo", users) is None


def test_secrets_replace_demo_accounts():
    secrets = {"auth": {"users": {"Anna": {"name": "Anna Rossi", "role": "Dispatcher",
                                           "password_hash": auth.hash_password("pw")}}}}
    users, is_demo = auth.load_users(secrets)
    assert not is_demo and set(users) == {"anna"}
    assert auth.authenticate("anna", "pw", users).initials == "AR"
    assert auth.authenticate("dispatcher", "dispatch-demo", users) is None


def test_misconfigured_accounts_are_refused():
    pw = auth.hash_password("pw")
    users = {"x": {"role": "Admin", "password_hash": pw},          # unknown role
             "y": {"role": "Driver", "password_hash": pw}}         # driver without a truck
    assert auth.authenticate("x", "pw", users) is None
    assert auth.authenticate("y", "pw", users) is None


def test_throttle_locks_after_repeated_failures():
    clock = [100.0]
    state = {}
    t = auth.Throttle(state, now=lambda: clock[0])
    for _ in range(auth.MAX_FAILURES - 1):
        t.failure()
    assert t.locked_for() == 0
    t.failure()
    assert t.locked_for() == auth.LOCKOUT_S
    clock[0] += auth.LOCKOUT_S
    assert t.locked_for() == 0
    t.failure(); t.success()
    assert state["auth_failures"] == 0
