# Offline decoder regression tests

Use Python 3.13 or newer and an isolated virtual environment:

```sh
python -m pip install catgenie==0.1.6
python -B -m unittest discover -s tests -v
```

The tests use the actual pinned CatGenie Pydantic models and integration
adapter. Payloads are synthetic. Home Assistant and HTTP/crypto import seams
are temporarily stubbed; no cloud requests or device commands are made.
The stubs and import search path are restored after loading the adapter.
These unit tests do not replace testing inside a running Home Assistant instance.

For offline review against an already-extracted copy of the pinned dependency,
set `CATGENIE_TEST_DEPENDENCY` to the directory containing its `catgenie` package.
The installed dependency is used when that variable is unset.
