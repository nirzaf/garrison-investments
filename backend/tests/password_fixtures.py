"""Fast bcrypt hashes for synthetic test accounts."""

import bcrypt


def hash_fixture_password(password: str) -> str:
    # These accounts exist only in isolated test databases. The application
    # still verifies the bcrypt hash through its normal login code.
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=4)).decode("ascii")
