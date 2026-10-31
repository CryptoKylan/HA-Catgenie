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

The suite covers strict integer-state validation, both field aliases, inherited
model fields and schedule normalization; error codes 2 and 5 in their separate
namespace; vendor text, unmapped and mixed codes; normal operation and fault
clearing; missing/offline data; stable entity identities; and long error states
with complete diagnostic details. It also replays a synthetic normal-cycle
sequence through the actual sensor classes without changing progress semantics.
