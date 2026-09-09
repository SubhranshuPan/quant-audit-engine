"""Test-wide setup.

The rate limiter counts every request across the whole session, and the suite
fires several hundred in a few seconds -- far above any sane production limit.
It is raised here rather than removed so the middleware still runs on every
test, and `test_rate_limit.py` exercises the real throttling behaviour with its
own low limit.

This must happen before `app.main` is imported, because the middleware reads
the setting when the app is constructed. pytest loads conftest first, so it does.
"""

import os

os.environ.setdefault("QUANT_RATE_LIMIT_PER_MINUTE", "1000000")
